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
