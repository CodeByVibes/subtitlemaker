"""The standalone apps run on the CPU only, even on a machine with an NVIDIA GPU."""

import logging
import sys

import pytest

from subtitlemaker import _packaged, transcribe
from subtitlemaker._packaged import (
    CPU_ONLY_NOTE,
    USE_CUDA_VARIABLE,
    cpu_only_build,
    is_packaged_app,
)
from subtitlemaker.config import ModelConfig


@pytest.fixture
def gpu_visible(monkeypatch):
    """CTranslate2 reports one CUDA device, as it does on a machine with an NVIDIA GPU."""

    monkeypatch.setattr(transcribe.ctranslate2, "get_cuda_device_count", lambda: 1)


@pytest.fixture
def packaged(monkeypatch):
    """Pretend to be a PyInstaller app (it sets `sys.frozen`)."""

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv(USE_CUDA_VARIABLE, raising=False)


# --- telling the two apart ------------------------------------------------------------------


def test_running_from_python_is_not_a_packaged_app():
    assert is_packaged_app() is False
    assert cpu_only_build() is False


def test_a_frozen_program_is_a_packaged_app_and_cpu_only(packaged):
    assert is_packaged_app() is True
    assert cpu_only_build() is True


def test_cuda_can_be_allowed_in_a_packaged_app_on_purpose(packaged, monkeypatch):
    monkeypatch.setenv(USE_CUDA_VARIABLE, "1")

    assert is_packaged_app() is True
    assert cpu_only_build() is False


@pytest.mark.parametrize("value", ["", "0", "yes", "true"])
def test_only_the_exact_value_allows_cuda(packaged, monkeypatch, value):
    monkeypatch.setenv(USE_CUDA_VARIABLE, value)

    assert cpu_only_build() is True


# --- the GPU is never used ---------------------------------------------------------------------


def test_a_visible_gpu_is_still_not_available_to_a_packaged_app(gpu_visible, packaged):
    assert transcribe.cuda_available() is False


def test_a_visible_gpu_is_available_when_not_packaged(gpu_visible):
    assert transcribe.cuda_available() is True


def test_cuda_follows_the_gpu_again_when_allowed(gpu_visible, packaged, monkeypatch):
    monkeypatch.setenv(USE_CUDA_VARIABLE, "1")

    assert transcribe.cuda_available() is True


def test_automatic_settings_choose_the_cpu_and_the_small_model(gpu_visible, packaged):
    # The case that matters: with the GPU model chosen, 2.9 GB would be downloaded
    # before CUDA turned out to be unusable.
    chosen = transcribe.resolve_model_config(ModelConfig())

    assert (chosen.device, chosen.name, chosen.compute_type) == ("cpu", "small", "int8")


def test_not_packaged_the_same_machine_gets_the_gpu_model(gpu_visible):
    chosen = transcribe.resolve_model_config(ModelConfig())

    assert (chosen.device, chosen.name) == ("cuda", "large-v3")


def test_the_cpu_choice_is_explained_in_the_apps_own_terms(gpu_visible, packaged, caplog):
    with caplog.at_level(logging.WARNING, logger="subtitlemaker"):
        transcribe.resolve_model_config(ModelConfig())

    text = caplog.text

    assert "CPU-only app build" in text and _packaged.PIP_HINT in text
    assert "no CUDA device found" not in text  # there is one: the app just does not use it


def test_asking_for_the_gpu_explicitly_is_refused_with_a_way_forward(gpu_visible, packaged):
    with pytest.raises(transcribe.ModelError) as error:
        transcribe.resolve_model_config(ModelConfig(device="cuda"))

    assert CPU_ONLY_NOTE in str(error.value)
    assert "device auto or cpu" in str(error.value)


def test_the_message_for_a_normal_install_is_unchanged(monkeypatch):
    monkeypatch.setattr(transcribe.ctranslate2, "get_cuda_device_count", lambda: 0)

    with pytest.raises(transcribe.ModelError, match="no CUDA device was found"):
        transcribe.resolve_model_config(ModelConfig(device="cuda"))
