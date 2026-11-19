"""Whisper model access and language handling."""

import io
import logging
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import ctranslate2
import numpy as np
from faster_whisper import WhisperModel, available_models

from ._cuda import preload_cuda_libs
from ._packaged import CPU_ONLY_NOTE, cpu_only_build
from .config import ModelConfig, SubtitleStyle
from .languages import parse_language_argument  # noqa: F401  (kept importable here)

log = logging.getLogger(__name__)

# user/model, as used on the Hugging Face Hub
_REPO_ID = re.compile(r"[A-Za-z0-9][\w.-]*/[\w.-]+")

# Defaults used when the model or compute type is left on "auto".
DEFAULT_MODEL = {"cuda": "large-v3", "cpu": "small"}
DEFAULT_COMPUTE_TYPE = {"cuda": "float16", "cpu": "int8"}

CUDA_HINT = (
    "To use the GPU, install the CUDA 12 libraries with "
    "'pip install subtitlemaker[cuda]' (or use --device cpu)."
)


class ModelError(RuntimeError):
    """A model could not be selected or loaded. The message is user-facing."""


def cuda_available() -> bool:
    """True if CTranslate2 can see at least one CUDA device (never in the CPU-only app build)."""

    if cpu_only_build():
        return False

    try:
        return bool(ctranslate2.get_cuda_device_count() > 0)

    except RuntimeError:
        return False


def resolve_model_config(config: ModelConfig, cuda: bool | None = None) -> ModelConfig:
    """
    Turn "auto" settings into concrete ones.

    - device:       cuda if a GPU is visible, otherwise cpu (with a warning)
    - model:        large-v3 on cuda, small on cpu
    - compute type: float16 on cuda, int8 on cpu

    `cuda` overrides GPU detection (used by tests). Raises `ModelError`
    for choices that cannot work: --device cuda without a GPU, an unknown
    model name, or a compute type the device does not support.
    """

    if cuda is None:
        cuda = cuda_available()

    if config.device == "auto":

        if cuda:
            device = "cuda"

        else:
            device = "cpu"

            if cpu_only_build():
                log.warning("using the CPU. %s", CPU_ONLY_NOTE)

            else:
                log.warning(
                    "no CUDA device found, using the CPU. "
                    "Transcription will be much slower."
                )

    elif config.device == "cuda" and not cuda:

        if cpu_only_build():
            raise ModelError(
                f"The GPU cannot be used (device cuda). {CPU_ONLY_NOTE} "
                "Or choose device auto or cpu."
            )

        raise ModelError(
            "--device cuda was requested but no CUDA device was found. "
            "Use --device auto or --device cpu."
        )

    else:
        device = config.device

    name = config.name

    if name == "auto":
        name = DEFAULT_MODEL[device]

    elif name not in available_models() and not Path(name).exists():

        if _REPO_ID.fullmatch(name):

            # "models/mine" looks like a repo id, but if "models" is a
            # folder here, a mistyped path is far more likely.
            if Path(name.split("/")[0]).is_dir():
                raise ModelError(f"model path not found: {name}")

            # otherwise a Hugging Face repo id, downloaded on first use

        elif "/" in name or name.startswith("."):
            raise ModelError(f"model path not found: {name}")

        else:
            raise ModelError(
                f"unknown model '{name}'. Use one of: "
                f"{', '.join(available_models())}; a Hugging Face repo "
                f"id such as 'user/model'; or a path to a converted model."
            )

    compute_type = config.compute_type

    if compute_type == "auto":
        compute_type = DEFAULT_COMPUTE_TYPE[device]

    else:
        supported = ctranslate2.get_supported_compute_types(device)

        if compute_type not in supported:
            raise ModelError(
                f"compute type '{compute_type}' is not supported on "
                f"{device}. Supported: {', '.join(sorted(supported))}."
            )

    return replace(
        config,
        name=name,
        device=device,
        compute_type=compute_type,
    )


def load_model(
    config: ModelConfig,
    allow_cpu_fallback: bool = False,
    requested: ModelConfig | None = None,
    on_download: "DownloadProgress | None" = None,
) -> tuple[WhisperModel, ModelConfig]:
    """
    Load the model described by a resolved `ModelConfig`.

    Returns `(model, config_used)`. With `allow_cpu_fallback`, a CUDA
    failure (typically missing CUDA libraries) falls back to the CPU with
    a warning instead of failing; the returned config shows what was used.

    `requested` is the config as the user gave it, before "auto" was
    resolved. On a fallback, the model and compute type are only swapped
    for CPU defaults where the user left them on "auto"; without it,
    everything is treated as automatic.
    """

    if config.device == "cuda":
        preload_cuda_libs()

    try:
        return _create(config, on_download), config

    except Exception as e:

        # Hugging Face raises its own types (offline, unknown repo, bad id),
        # so only a RuntimeError on the GPU is treated as a CUDA problem.
        if config.device != "cuda" or not isinstance(e, RuntimeError):
            raise _load_error(config.name, e) from e

        if not allow_cpu_fallback:
            raise ModelError(
                f"couldn't start CUDA: {e}\n{CUDA_HINT}"
            ) from e

        log.warning("CUDA could not be used (%s)", e)
        log.warning(CUDA_HINT)

        # The CUDA defaults no longer fit: pick CPU ones, but never override
        # what the user chose themselves.
        name_is_auto = requested is None or requested.name == "auto"
        compute_is_auto = requested is None or requested.compute_type == "auto"

        fallback = replace(
            config,
            device="cpu",
            name=DEFAULT_MODEL["cpu"] if name_is_auto else config.name,
            compute_type=(
                DEFAULT_COMPUTE_TYPE["cpu"] if compute_is_auto else config.compute_type
            ),
        )

        if not compute_is_auto:
            supported = ctranslate2.get_supported_compute_types("cpu")

            if fallback.compute_type not in supported:
                raise ModelError(
                    f"couldn't start CUDA: {e}\n{CUDA_HINT}\n"
                    f"The CPU can't be used instead because compute type "
                    f"'{fallback.compute_type}' is not supported there."
                ) from e

        log.warning(
            "falling back to the CPU with model '%s'.", fallback.name
        )

        try:
            return _create(fallback, on_download), fallback

        except Exception as e2:
            raise _load_error(fallback.name, e2) from e2


def load_for_run(
    model_config: ModelConfig,
    multilingual: bool,
    task: str,
    style: SubtitleStyle,
    on_download: "DownloadProgress | None" = None,
) -> tuple[WhisperModel, ModelConfig]:
    """
    Resolve and load the model for a run, logging what is used.

    Returns `(model, config_used)`. Raises `ModelError` (message ready to
    show) if the model cannot be chosen or loaded.
    """

    # A GPU that turns out to be unusable only falls back to the CPU when
    # the device was left on auto.
    allow_cpu_fallback = model_config.device == "auto"

    # What the user asked for, before "auto" is resolved: a CPU fallback
    # must not replace a model or compute type they chose.
    requested_config = model_config

    model_config = resolve_model_config(model_config)

    log.info("Model:          %s", model_config.name)
    log.info("Device:         %s", model_config.device)
    log.info("Compute type:   %s", model_config.compute_type)

    if multilingual and task == "translate":
        log.warning(
            "task=translate turns every segment into English."
        )

    log.debug("Subtitle configuration:")
    log.debug("  Max line length:  %s", style.max_line_length)
    log.debug("  Max lines:        %s", style.max_lines)
    log.debug("  Max CPS:          %g", style.max_cps)
    log.debug("  Min duration:     %ss", style.min_duration)
    log.debug("  Max duration:     %ss", style.max_duration)
    log.debug("  Minimum gap:      %ss", style.min_gap)
    log.debug("  Max pause:        %ss", style.max_pause)
    log.debug("  Linger:           %ss", style.linger)
    log.debug("  Close gaps under: %ss", style.close_gap)

    log.info("Loading Whisper model...")

    return load_model(
        model_config,
        allow_cpu_fallback=allow_cpu_fallback,
        requested=requested_config,
        on_download=on_download,
    )


def _load_error(name: str, error: BaseException) -> ModelError:
    """A `ModelError` for any failure to create a model, with a hint."""

    return ModelError(
        f"couldn't load model '{name}': {error}\n"
        f"Models are downloaded on first use and need an internet "
        f"connection. Check the model name or path."
    )


DownloadProgress = Callable[[str, int, int], None]

# Approximate download sizes in MB, for the notice only.
MODEL_SIZE_MB = {
    "tiny": 73,
    "tiny.en": 73,
    "base": 141,
    "base.en": 141,
    "small": 462,
    "small.en": 462,
    "medium": 1500,
    "medium.en": 1500,
    "large-v3": 2900,
    "turbo": 1600,
    "large-v3-turbo": 1600,
}

# The files faster-whisper itself fetches.
_MODEL_FILES = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


def _repo_id(name: str) -> str | None:
    """The Hugging Face repository for a model name, or None if it is not one."""

    if "/" in name:
        return name

    try:
        from faster_whisper.utils import _MODELS

    except ImportError:  # pragma: no cover (private name moved)
        return f"Systran/faster-whisper-{name}" if name in available_models() else None

    return _MODELS.get(name)


def is_downloaded(name: str) -> bool:
    """True if the model is a local folder or already in the Hugging Face cache."""

    if Path(name).is_dir():
        return True

    from faster_whisper.utils import download_model

    try:
        download_model(name, local_files_only=True)

    except Exception:
        return False

    return True


def download_model_with_progress(name: str, on_download: DownloadProgress) -> None:
    """
    Fetch `name` into the cache if it is missing, reporting `(name, done, total)` bytes.

    Does nothing for local folders, cached models and names that are not
    models (loading then reports that properly).
    """

    repo = _repo_id(name)

    if repo is None or is_downloaded(name):
        return

    size = MODEL_SIZE_MB.get(name)
    about = f" (about {size} MB)" if size else ""
    log.info("Downloading the %s model%s. This happens once.", name, about)

    import huggingface_hub
    from tqdm.std import tqdm

    bars: list = []
    reported = [-1]

    class ByteBar(tqdm):
        """A silent bar that forwards its byte counts."""

        def __init__(self, *args, **kwargs):
            kwargs["file"] = io.StringIO()
            super().__init__(*args, **kwargs)

            if self.unit == "B":
                bars.append(self)

        def update(self, n=1):
            result = super().update(n)

            if self in bars:
                _report(bars, reported, name, on_download)

            return result

        def display(self, *args, **kwargs):
            pass

    huggingface_hub.snapshot_download(
        repo, allow_patterns=_MODEL_FILES, tqdm_class=ByteBar
    )


def _report(bars: list, reported: list, name: str, on_download: DownloadProgress) -> None:
    """
    Tell the listener how far the download is, once per percent.

    huggingface_hub keeps two byte bars: the network transfer, which moves
    steadily, and the files written, which can jump at the end. Whichever
    is further along is the truth.
    """

    live = [bar for bar in bars if bar.total]

    if not live:
        return

    bar = max(live, key=lambda b: b.n / b.total)
    percent = int(100 * bar.n / bar.total)

    if percent != reported[0] or bar.n >= bar.total:
        reported[0] = percent
        on_download(name, int(bar.n), int(bar.total))


def _create(config: ModelConfig, on_download: DownloadProgress | None = None) -> WhisperModel:

    if on_download is not None:
        download_model_with_progress(config.name, on_download)

    model = WhisperModel(
        config.name,
        device=config.device,
        compute_type=config.compute_type,
    )

    if config.device == "cuda":
        _warm_up(model)

    return model


def _warm_up(model: WhisperModel) -> None:
    """
    Run one tiny encode on the GPU.

    CTranslate2 loads cuBLAS and cuDNN lazily, so missing libraries (or too
    little GPU memory) would otherwise only surface in the middle of the
    first transcription. Raises RuntimeError in that case.
    """

    silence = np.zeros(
        (1, model.model.n_mels, model.feature_extractor.nb_max_frames),
        dtype=np.float32,
    )

    model.model.encode(
        ctranslate2.StorageView.from_array(silence),
        to_cpu=True,
    )
