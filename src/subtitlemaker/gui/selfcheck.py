"""`subtitlemaker-gui --self-check`: does everything the app needs work?

A packaged app fails in ways its source tree never does: a data file that was
not bundled (the voice-activity model, the SVG icon plugin) or a native
library that will not load. Those only show when the feature is first used,
so the package is checked as a whole, once, before anyone downloads it.
"""

import importlib
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from .. import __version__


@dataclass(frozen=True)
class Check:
    """The outcome of one check."""

    name: str
    ok: bool
    detail: str

    def line(self) -> str:
        return f"{'ok  ' if self.ok else 'FAIL'} {self.name}: {self.detail}"


# Modules the app imports at run time, whose version (when they have one) is reported.
_MODULES = (
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",  # not imported by the code: its plugin draws the app icon
    "ctranslate2",
    "faster_whisper",
    "av",
    "numpy",
    "onnxruntime",
    "tokenizers",
    "huggingface_hub",
    "rich",
)


def run_checks(audio: str | None = None, model: str = "tiny") -> list[Check]:
    """Run every check. A failing check is recorded, never raised, so the rest still run."""

    # A check must not open a window on someone's screen.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    results: list[Check] = []

    def check(name: str, function: Callable[[], str]) -> None:

        try:
            results.append(Check(name, True, function()))

        except Exception as e:
            results.append(Check(name, False, f"{type(e).__name__}: {e}"))

    check("version", lambda: __version__)

    for module in _MODULES:
        check(f"import {module}", partial(_import, module))

    check("voice activity model present", _vad_model)
    check("voice activity model loads", _vad_session)
    check("CTranslate2 on the CPU", _ctranslate2)
    check("packaged app stays on the CPU", _packaged_uses_cpu)
    check("versions for a bug report", _versions)
    check("window", _window)
    check("device", _device)

    if audio is None:
        results.append(Check("transcription", True, "skipped (no --audio given)"))

    else:
        check("transcription", lambda: _transcription(Path(audio), model))

    return results


def run_self_check(
    audio: str | None = None, model: str = "tiny", report: str | None = None
) -> int:
    """Run the checks, print the report, and return 0 if all passed (else 1)."""

    results = run_checks(audio, model)
    text = "\n".join(result.line() for result in results)
    passed = all(result.ok for result in results)

    summary = "self-check passed" if passed else "self-check FAILED"
    text = f"subtitlemaker-gui {__version__}\n{text}\n{summary}"

    print(text, flush=True)

    if report:
        Path(report).write_text(text + "\n", encoding="utf-8")

    return 0 if passed else 1


# --- the checks ------------------------------------------------------------------------


def _import(name: str) -> str:
    module = importlib.import_module(name)
    version = getattr(module, "__version__", None) or getattr(module, "version", None)

    return str(version) if isinstance(version, str) else "imported"


def _vad_path() -> Path:
    from faster_whisper.utils import get_assets_path

    found = sorted(Path(get_assets_path()).glob("silero_vad*.onnx"))

    if not found:
        raise FileNotFoundError(f"no silero_vad*.onnx in {get_assets_path()}")

    return found[0]


def _vad_model() -> str:
    path = _vad_path()

    return f"{path.name} ({path.stat().st_size // 1024} KiB)"


def _vad_session() -> str:
    import onnxruntime

    onnxruntime.InferenceSession(str(_vad_path()), providers=["CPUExecutionProvider"])

    return "onnxruntime ran it"


def _ctranslate2() -> str:
    import ctranslate2

    types = sorted(ctranslate2.get_supported_compute_types("cpu"))

    if not types:
        raise RuntimeError("no compute types on the CPU")

    return ", ".join(types)


def _versions() -> str:
    """A packaged app has no package metadata: the bug report details must still know the
    versions of what the app is built on."""

    from .about_info import package_version

    found = {
        "faster-whisper": package_version("faster-whisper"),
        "CTranslate2": package_version("ctranslate2"),
    }
    unknown = [name for name, version in found.items() if version == "unknown"]

    if unknown:
        raise RuntimeError(f"version unknown for: {', '.join(unknown)}")

    return ", ".join(f"{name} {version}" for name, version in found.items())


def _packaged_uses_cpu() -> str:
    """The standalone app has no CUDA libraries, so it must choose the CPU and its model,
    even on a machine whose NVIDIA GPU it can see (see `_packaged`)."""

    from .._packaged import cpu_only_build, is_packaged_app
    from ..config import ModelConfig
    from ..transcribe import resolve_model_config

    if not is_packaged_app():
        return "skipped (not a packaged app)"

    if not cpu_only_build():
        return "skipped (CUDA allowed by SUBTITLEMAKER_USE_CUDA)"

    chosen = resolve_model_config(ModelConfig())

    if (chosen.device, chosen.name, chosen.compute_type) != ("cpu", "small", "int8"):
        raise RuntimeError(
            f"automatic settings chose {chosen.name} on {chosen.device} ({chosen.compute_type}), "
            "not small on cpu"
        )

    return "automatic settings choose the small model on the cpu"


def _window() -> str:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow
    from .resources import ICON_PATH

    app = QApplication.instance() or QApplication([])

    if QIcon(str(ICON_PATH)).pixmap(64, 64).isNull():
        raise RuntimeError(f"the icon {ICON_PATH.name} does not draw (is the SVG plugin bundled?)")

    window = MainWindow()
    window.show()
    app.processEvents()

    try:
        titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]

    finally:
        window.close()

    return f"main window opened ({', '.join(titles)}), icon draws"


def _device() -> str:
    from .settings_panel import device_summary

    return device_summary()


def _transcription(audio: Path, model: str) -> str:
    """Transcribe a short clip on the CPU, start to finish, and check subtitles came out."""

    from ..config import ModelConfig, SubtitleStyle
    from ..pipeline import Options, process_file
    from ..transcribe import load_for_run

    if not audio.is_file():
        raise FileNotFoundError(f"audio file not found: {audio}")

    # The CPU on purpose, whatever this machine has: that is what a packaged app does.
    config = ModelConfig(name=model, device="cpu", compute_type="int8")
    style = SubtitleStyle()

    loaded, used = load_for_run(config, False, "transcribe", style)

    options = Options(
        style=style,
        model_config=used,
        task="transcribe",
        languages=[],
        language_hint=None,
        multilingual=False,
        condition_on_previous_text=True,
        detect_segments=1,
        detect_threshold=0.5,
    )

    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / "check.srt"
        result = process_file(loaded, audio, {"srt": output}, options)

        if not result.subtitles:
            raise RuntimeError("no subtitles were produced")

        if not output.is_file() or not output.read_text(encoding="utf-8").strip():
            raise RuntimeError("the subtitle file is missing or empty")

    first = result.subtitles[0]["text"].replace("\n", " ")

    return (
        f"{len(result.subtitles)} subtitles in {result.language} on the {used.device}: "
        f'"{first}"'
    )
