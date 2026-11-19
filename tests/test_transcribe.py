import logging

import pytest

from subtitlemaker.config import ModelConfig
from subtitlemaker.transcribe import ModelError, parse_language_argument, resolve_model_config


@pytest.mark.parametrize(
    ("cuda", "model", "expected"),
    [
        (True, "auto", ("large-v3", "cuda", "float16")),
        (False, "auto", ("small", "cpu", "int8")),
        (True, "tiny", ("tiny", "cuda", "float16")),
        (False, "turbo", ("turbo", "cpu", "int8")),
    ],
)
def test_auto_resolution(cuda, model, expected):
    resolved = resolve_model_config(ModelConfig(name=model), cuda=cuda)

    assert (resolved.name, resolved.device, resolved.compute_type) == expected


def test_no_gpu_with_auto_warns_and_uses_cpu(caplog):
    with caplog.at_level(logging.WARNING):
        resolved = resolve_model_config(ModelConfig(), cuda=False)

    assert resolved.device == "cpu"
    assert "no CUDA device" in caplog.text


def test_explicit_cpu_does_not_warn(caplog):
    with caplog.at_level(logging.WARNING):
        resolved = resolve_model_config(ModelConfig(device="cpu"), cuda=True)

    assert resolved.device == "cpu"
    assert caplog.text == ""


def test_explicit_cuda_without_gpu_is_an_error():
    with pytest.raises(ModelError, match="no CUDA device"):
        resolve_model_config(ModelConfig(device="cuda"), cuda=False)


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("nonsense", "unknown model"),
        ("./missing-model", "path not found"),
        ("/abs/missing", "path not found"),
        ("../missing", "path not found"),
    ],
)
def test_bad_model_names(name, message):
    with pytest.raises(ModelError, match=message):
        resolve_model_config(ModelConfig(name=name), cuda=False)


def test_hugging_face_repo_id_is_accepted():
    resolved = resolve_model_config(ModelConfig(name="Systran/faster-whisper-large-v3"), cuda=False)

    assert resolved.name == "Systran/faster-whisper-large-v3"


def test_existing_local_path_is_accepted(tmp_path):
    resolved = resolve_model_config(ModelConfig(name=str(tmp_path)), cuda=False)

    assert resolved.name == str(tmp_path)


def test_unsupported_compute_type_is_an_error():
    with pytest.raises(ModelError, match="not supported on cpu"):
        resolve_model_config(ModelConfig(device="cpu", compute_type="float16"), cuda=False)


def test_supported_compute_type_is_kept():
    resolved = resolve_model_config(ModelConfig(device="cpu", compute_type="float32"), cuda=False)

    assert resolved.compute_type == "float32"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ([], False)),
        ("", ([], False)),
        ("he", (["he"], False)),
        ("HE", (["he"], False)),
        ("he,en", (["he", "en"], True)),
        ("en sv", (["en", "sv"], True)),
        ("en, en", (["en"], False)),
    ],
)
def test_parse_language_argument(value, expected):
    assert parse_language_argument(value) == expected


def test_unknown_language_is_rejected():
    with pytest.raises(ValueError, match="zz"):
        parse_language_argument("en,zz")


def test_a_folder_prefix_means_a_mistyped_path_not_a_hub_id(tmp_path, monkeypatch):
    (tmp_path / "models").mkdir()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ModelError, match="path not found"):
        resolve_model_config(ModelConfig(name="models/mine"), cuda=False)


# --- loading failures --------------------------------------------------------


def _hub_errors():
    from huggingface_hub.errors import LocalEntryNotFoundError

    return [
        LocalEntryNotFoundError("offline"),
        ConnectionError("no route to host"),
        ValueError("bad id"),
        OSError("disk"),
        RuntimeError("broken"),
    ]


@pytest.mark.parametrize("error", _hub_errors(), ids=lambda e: type(e).__name__)
def test_any_load_failure_on_the_cpu_is_a_model_error(monkeypatch, error):
    from subtitlemaker import transcribe

    def fail(config, on_download=None):
        raise error

    monkeypatch.setattr(transcribe, "_create", fail)

    with pytest.raises(ModelError, match="need an internet connection") as info:
        transcribe.load_model(ModelConfig(name="x/y", device="cpu", compute_type="int8"))

    assert str(error) in str(info.value)


def test_a_non_runtime_error_on_cuda_is_not_mistaken_for_a_cuda_problem(monkeypatch):
    from subtitlemaker import transcribe

    monkeypatch.setattr(transcribe, "preload_cuda_libs", lambda: None)

    def fail(config, on_download=None):
        raise ValueError("bad id")

    monkeypatch.setattr(transcribe, "_create", fail)

    with pytest.raises(ModelError) as info:
        transcribe.load_model(
            ModelConfig(name="x/y", device="cuda", compute_type="float16"),
            allow_cpu_fallback=True,
        )

    assert "CUDA" not in str(info.value)


def test_a_failing_cpu_fallback_is_a_model_error(monkeypatch):
    from subtitlemaker import transcribe

    monkeypatch.setattr(transcribe, "preload_cuda_libs", lambda: None)

    def fail(config, on_download=None):
        raise RuntimeError("cuda") if config.device == "cuda" else ValueError("offline")

    monkeypatch.setattr(transcribe, "_create", fail)

    with pytest.raises(ModelError, match="offline"):
        transcribe.load_model(
            ModelConfig(name="large-v3", device="cuda", compute_type="float16"),
            allow_cpu_fallback=True,
        )


# --- CPU fallback keeps what the user chose ------------------------------------


def _cuda_fails(monkeypatch):
    from subtitlemaker import transcribe

    created = []

    def create(config, on_download=None):
        if config.device == "cuda":
            raise RuntimeError("no cublas")

        created.append(config)
        return object()

    monkeypatch.setattr(transcribe, "preload_cuda_libs", lambda: None)
    monkeypatch.setattr(transcribe, "_create", create)

    return created


def test_fallback_uses_cpu_defaults_when_everything_was_automatic(monkeypatch):
    from subtitlemaker import transcribe

    created = _cuda_fails(monkeypatch)
    resolved = ModelConfig(name="large-v3", device="cuda", compute_type="float16")

    _, used = transcribe.load_model(resolved, allow_cpu_fallback=True, requested=ModelConfig())

    assert (used.device, used.name, used.compute_type) == ("cpu", "small", "int8")
    assert created == [used]


def test_fallback_keeps_an_explicitly_chosen_model(monkeypatch):
    from subtitlemaker import transcribe

    _cuda_fails(monkeypatch)
    resolved = ModelConfig(name="large-v3", device="cuda", compute_type="float16")
    requested = ModelConfig(name="large-v3")

    _, used = transcribe.load_model(resolved, allow_cpu_fallback=True, requested=requested)

    assert used.name == "large-v3"
    assert used.compute_type == "int8"


def test_fallback_keeps_an_explicitly_chosen_compute_type(monkeypatch):
    from subtitlemaker import transcribe

    _cuda_fails(monkeypatch)
    resolved = ModelConfig(name="large-v3", device="cuda", compute_type="int8_float32")
    requested = ModelConfig(compute_type="int8_float32")

    _, used = transcribe.load_model(resolved, allow_cpu_fallback=True, requested=requested)

    assert used.compute_type == "int8_float32"
    assert used.name == "small"


def test_fallback_refuses_a_compute_type_the_cpu_cannot_run(monkeypatch):
    from subtitlemaker import transcribe

    _cuda_fails(monkeypatch)
    monkeypatch.setattr(
        transcribe.ctranslate2, "get_supported_compute_types", lambda device: {"int8", "float32"}
    )
    resolved = ModelConfig(name="large-v3", device="cuda", compute_type="float16")
    requested = ModelConfig(compute_type="float16")

    with pytest.raises(ModelError, match="float16.*not supported"):
        transcribe.load_model(resolved, allow_cpu_fallback=True, requested=requested)


# --- downloading a missing model with progress (SUBMAKER-68) -----------------------


def test_a_cached_model_is_not_downloaded(monkeypatch):
    from subtitlemaker import transcribe

    monkeypatch.setattr(transcribe, "is_downloaded", lambda name: True)

    def boom(*args, **kwargs):
        raise AssertionError("must not download")

    monkeypatch.setattr("huggingface_hub.snapshot_download", boom)

    transcribe.download_model_with_progress("small", lambda *a: None)


def test_a_name_that_is_no_model_is_left_to_the_loader(monkeypatch):
    from subtitlemaker import transcribe

    def boom(*args, **kwargs):
        raise AssertionError("must not download")

    monkeypatch.setattr("huggingface_hub.snapshot_download", boom)

    transcribe.download_model_with_progress("no-such-model", lambda *a: None)


def test_a_local_folder_counts_as_downloaded(tmp_path):
    from subtitlemaker import transcribe

    assert transcribe.is_downloaded(str(tmp_path))


def test_a_model_missing_from_the_cache_is_not_downloaded_yet(monkeypatch):
    from subtitlemaker import transcribe

    def not_in_cache(name, local_files_only=False):
        assert local_files_only, "checking the cache must never download"
        raise OSError("not cached")

    monkeypatch.setattr("faster_whisper.utils.download_model", not_in_cache)

    assert not transcribe.is_downloaded("tiny")


def _fake_download(monkeypatch, steps):
    """Replace snapshot_download by one that drives the given tqdm class like the real one."""

    seen = {}

    def snapshot_download(repo, allow_patterns=None, tqdm_class=None):
        seen["repo"] = repo
        seen["patterns"] = allow_patterns
        transfer = tqdm_class(total=0, unit="B", desc="Downloading bytes")
        written = tqdm_class(total=0, unit="B", desc="Reconstructing")
        files = tqdm_class(total=2, unit="it", desc="Fetching 2 files")
        transfer.total = written.total = 1000

        for bar, n in steps:
            {"transfer": transfer, "written": written, "files": files}[bar].update(n)

    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_download)

    return seen


def test_download_reports_bytes_once_per_percent(monkeypatch):
    from subtitlemaker import transcribe

    monkeypatch.setattr(transcribe, "is_downloaded", lambda name: False)
    seen = _fake_download(
        monkeypatch,
        [("transfer", 1), ("transfer", 1), ("transfer", 400), ("files", 1), ("transfer", 598)],
    )
    reports = []

    transcribe.download_model_with_progress("small", lambda *a: reports.append(a))

    assert seen["repo"] == "Systran/faster-whisper-small"
    assert "model.bin" in seen["patterns"]
    # 0.1% and 0.2% are both 0 percent: one report; then 40.2%; then the end.
    assert reports == [("small", 1, 1000), ("small", 402, 1000), ("small", 1000, 1000)]


def test_download_follows_whichever_bar_is_further(monkeypatch):
    from subtitlemaker import transcribe

    monkeypatch.setattr(transcribe, "is_downloaded", lambda name: False)
    _fake_download(monkeypatch, [("transfer", 100), ("written", 500)])
    reports = []

    transcribe.download_model_with_progress("small", lambda *a: reports.append(a))

    assert reports[-1] == ("small", 500, 1000)


def test_download_announces_itself_in_the_log(monkeypatch, caplog):
    import logging

    from subtitlemaker import transcribe

    monkeypatch.setattr(transcribe, "is_downloaded", lambda name: False)
    _fake_download(monkeypatch, [])

    with caplog.at_level(logging.INFO):
        transcribe.download_model_with_progress("small", lambda *a: None)

    assert "Downloading the small model (about 462 MB). This happens once." in caplog.text


def test_create_downloads_only_when_asked(monkeypatch):
    from subtitlemaker import transcribe

    calls = []
    monkeypatch.setattr(
        transcribe, "download_model_with_progress", lambda name, cb: calls.append(name)
    )
    monkeypatch.setattr(transcribe, "WhisperModel", lambda *a, **k: object())

    config = ModelConfig(name="small", device="cpu", compute_type="int8")
    transcribe._create(config)
    assert calls == []

    transcribe._create(config, lambda *a: None)
    assert calls == ["small"]
