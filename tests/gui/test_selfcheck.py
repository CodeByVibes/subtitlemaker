"""`subtitlemaker-gui --self-check`: the check a packaged app runs on itself."""

import sys

import pytest

pytest.importorskip("PySide6")

from subtitlemaker import gui  # noqa: E402
from subtitlemaker.gui import selfcheck  # noqa: E402
from subtitlemaker.gui.selfcheck import Check, run_checks, run_self_check  # noqa: E402


def by_name(results):
    return {result.name: result for result in results}


@pytest.fixture
def audio(tmp_path, monkeypatch):
    monkeypatch.setattr("subtitlemaker.pipeline.get_duration", lambda path: 10.0)
    path = tmp_path / "clip.mp3"
    path.write_bytes(b"")  # never decoded: the model is fake

    return path


# --- the checks themselves --------------------------------------------------------------------


def test_everything_passes_in_a_working_install():
    results = run_checks()

    assert [r.name for r in results if not r.ok] == []
    names = by_name(results)

    assert "import ctranslate2" in names and "import PySide6.QtSvg" in names
    assert "voice activity model present" in names and "voice activity model loads" in names
    assert "CTranslate2 on the CPU" in names and "window" in names and "device" in names
    assert "int8" in names["CTranslate2 on the CPU"].detail  # what a CPU build needs
    assert names["transcription"].detail == "skipped (no --audio given)"


def test_the_main_window_and_its_icon_are_checked():
    window = by_name(run_checks())["window"]

    assert window.ok
    assert "Queue, Settings, Log" in window.detail and "icon draws" in window.detail


def test_a_whole_transcription_is_checked_when_an_audio_file_is_given(audio, fake_model):
    result = by_name(run_checks(str(audio), "tiny"))["transcription"]

    assert result.ok
    assert "1 subtitles in en on the cpu" in result.detail
    assert "Hello world." in result.detail  # what the (fake) model said


def test_the_transcription_uses_the_cpu_whatever_the_machine_has(audio, fake_model):
    run_checks(str(audio), "tiny")

    # A packaged app has no CUDA libraries: the check has to prove the CPU path works.
    assert fake_model.requested.device == "cpu"
    assert fake_model.requested.compute_type == "int8"


def test_the_transcription_leaves_nothing_behind(audio, fake_model, tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())

    run_checks(str(audio), "tiny")

    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_a_missing_audio_file_is_a_failure_not_a_crash(tmp_path):
    result = by_name(run_checks(str(tmp_path / "nothing.flac")))["transcription"]

    assert not result.ok and "not found" in result.detail


def test_a_model_that_produces_nothing_is_a_failure(audio, fake_model):
    fake_model.segments = []

    result = by_name(run_checks(str(audio), "tiny"))["transcription"]

    assert not result.ok and "no subtitles were produced" in result.detail


def test_a_subtitle_file_that_comes_out_empty_is_a_failure(audio, fake_model, monkeypatch):
    class Silent:
        def write(self, cues, path):
            open(path, "w").close()  # "succeeds", writes nothing

    monkeypatch.setattr("subtitlemaker.pipeline.FORMATS", {"srt": Silent()})

    result = by_name(run_checks(str(audio), "tiny"))["transcription"]

    assert not result.ok and "missing or empty" in result.detail


def test_the_check_never_opens_windows_on_a_screen_by_default(monkeypatch):
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    run_checks()

    import os

    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"


def test_a_platform_chosen_by_the_caller_is_respected(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "minimal")

    run_checks()

    import os

    assert os.environ["QT_QPA_PLATFORM"] == "minimal"


# --- failures are reported, and do not hide the rest ------------------------------------------


def test_a_missing_voice_activity_model_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr("faster_whisper.utils.get_assets_path", lambda: str(tmp_path))

    names = by_name(run_checks())

    assert not names["voice activity model present"].ok
    assert "no silero_vad" in names["voice activity model present"].detail
    assert not names["voice activity model loads"].ok
    assert names["window"].ok and names["import ctranslate2"].ok  # the rest still ran


def test_a_module_that_cannot_be_imported_is_reported(monkeypatch):
    monkeypatch.setattr(selfcheck, "_MODULES", ("no_such_module_anywhere", "json"))

    names = by_name(run_checks())

    assert not names["import no_such_module_anywhere"].ok
    assert "ModuleNotFoundError" in names["import no_such_module_anywhere"].detail
    assert names["import json"].ok


def test_an_icon_that_does_not_draw_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr("subtitlemaker.gui.resources.ICON_PATH", tmp_path / "missing.svg")

    window = by_name(run_checks())["window"]

    assert not window.ok and "does not draw" in window.detail


# --- the report and the exit code -------------------------------------------------------------


def test_a_passing_run_prints_a_report_and_returns_zero(capsys):
    code = run_self_check()

    out = capsys.readouterr().out

    assert code == 0
    assert out.startswith("subtitlemaker-gui ")
    assert "ok   version: " in out and out.rstrip().endswith("self-check passed")
    assert "FAIL" not in out


def test_a_failing_run_returns_one_and_says_so(capsys, monkeypatch):
    monkeypatch.setattr(selfcheck, "_MODULES", ("no_such_module_anywhere",))

    code = run_self_check()

    out = capsys.readouterr().out

    assert code == 1
    assert "FAIL import no_such_module_anywhere" in out
    assert out.rstrip().endswith("self-check FAILED")


def test_the_report_can_be_written_to_a_file(tmp_path):
    report = tmp_path / "report.txt"

    run_self_check(report=str(report))

    text = report.read_text(encoding="utf-8")

    assert text.startswith("subtitlemaker-gui ") and text.rstrip().endswith("self-check passed")


def test_a_line_shows_whether_the_check_passed():
    assert Check("a", True, "fine").line() == "ok   a: fine"
    assert Check("a", False, "broken").line() == "FAIL a: broken"


# --- the command line -------------------------------------------------------------------------


def test_self_check_is_started_from_the_command_line(monkeypatch):
    calls = []
    monkeypatch.setattr(selfcheck, "run_self_check", lambda **kwargs: calls.append(kwargs) or 7)

    code = gui.main(["--self-check", "--audio", "a.flac", "--model", "base", "--report", "r.txt"])

    assert code == 7
    assert calls == [{"audio": "a.flac", "model": "base", "report": "r.txt"}]


def test_the_model_defaults_to_tiny(monkeypatch):
    calls = []
    monkeypatch.setattr(selfcheck, "run_self_check", lambda **kwargs: calls.append(kwargs) or 0)

    gui.main(["--self-check"])

    assert calls[0]["model"] == "tiny" and calls[0]["audio"] is None


def test_arguments_for_qt_are_passed_on_to_it(monkeypatch):
    calls = []
    monkeypatch.setattr("subtitlemaker.gui.app.run", lambda argv: calls.append(argv) or 0)

    assert gui.main(["-platform", "offscreen", "--style", "fusion"]) == 0

    assert calls[0][1:] == ["-platform", "offscreen", "--style", "fusion"]


def test_without_arguments_the_app_just_starts(monkeypatch):
    calls = []
    monkeypatch.setattr("subtitlemaker.gui.app.run", lambda argv: calls.append(argv) or 0)

    gui.main([])

    assert len(calls) == 1 and len(calls[0]) == 1


def test_the_versions_for_a_bug_report_are_checked_and_known():
    result = by_name(run_checks())["versions for a bug report"]

    assert result.ok
    assert "faster-whisper 1." in result.detail and "CTranslate2 4." in result.detail


def test_unknown_versions_fail_the_check(monkeypatch):
    monkeypatch.setattr("subtitlemaker.gui.about_info.package_version", lambda *a, **k: "unknown")

    result = by_name(run_checks())["versions for a bug report"]

    assert not result.ok
    assert "faster-whisper" in result.detail and "CTranslate2" in result.detail


# --- the packaged app stays on the CPU --------------------------------------------------------


def test_the_cpu_check_is_skipped_when_not_packaged():
    result = by_name(run_checks())["packaged app stays on the CPU"]

    assert result.ok and result.detail == "skipped (not a packaged app)"


def test_a_packaged_app_on_a_gpu_machine_passes_by_choosing_the_cpu(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("SUBTITLEMAKER_USE_CUDA", raising=False)
    monkeypatch.setattr("subtitlemaker.transcribe.ctranslate2.get_cuda_device_count", lambda: 1)

    result = by_name(run_checks())["packaged app stays on the CPU"]

    assert result.ok and "small model on the cpu" in result.detail


def test_a_packaged_app_that_would_use_the_gpu_fails_the_check(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("SUBTITLEMAKER_USE_CUDA", raising=False)
    monkeypatch.setattr("subtitlemaker.transcribe.cuda_available", lambda: True)  # the bug

    result = by_name(run_checks())["packaged app stays on the CPU"]

    assert not result.ok and "large-v3 on cuda" in result.detail


def test_the_check_steps_aside_when_cuda_is_allowed(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("SUBTITLEMAKER_USE_CUDA", "1")

    result = by_name(run_checks())["packaged app stays on the CPU"]

    assert result.ok and "SUBTITLEMAKER_USE_CUDA" in result.detail
