"""Several inputs, several formats, and what happens when things go wrong."""

import os

import pytest


@pytest.fixture
def library(tmp_path):
    """a.mp3, b.mp4 and notes.txt in one folder, c.wav in a sub folder."""

    root = tmp_path / "library"
    (root / "sub").mkdir(parents=True)

    for name in ("a.mp3", "b.mp4", "notes.txt", "sub/c.wav"):
        (root / name).write_bytes(b"")

    return root


def names(folder):
    return sorted(p.name for p in folder.iterdir() if p.is_file())


# --- output formats ---------------------------------------------------------


def test_format_flag_writes_every_requested_format(run, fake_model, library):
    assert run(library / "a.mp3", "-q", "-f", "srt,vtt,txt") == 0

    assert {"a.srt", "a.vtt", "a.txt"} <= set(names(library))
    assert (library / "a.vtt").read_text().startswith("WEBVTT")
    assert (library / "a.txt").read_text() == "Hello world.\n"


def test_default_format_is_srt_only(run, fake_model, library):
    run(library / "a.mp3", "-q")

    assert names(library) == ["a.mp3", "a.srt", "b.mp4", "notes.txt"]


def test_unknown_format_is_a_usage_error(run, fake_model, library):
    with pytest.raises(SystemExit) as exit_info:
        run(library / "a.mp3", "-f", "ass")

    assert exit_info.value.code == 2


def test_output_names_the_file_exactly_for_one_format(run, fake_model, library, tmp_path):
    out = tmp_path / "result.subs"

    assert run(library / "a.mp3", "-q", "-o", out) == 0

    assert out.read_text().startswith("1\n")  # SRT content, name kept as given


def test_output_is_a_base_name_for_several_formats(run, fake_model, library, tmp_path):
    assert run(library / "a.mp3", "-q", "-f", "srt,vtt", "-o", tmp_path / "result.srt") == 0

    assert (tmp_path / "result.srt").exists()
    assert (tmp_path / "result.vtt").exists()


# --- finding inputs ---------------------------------------------------------


def test_directory_means_the_media_files_in_it(run, fake_model, library):
    assert run(library, "-q") == 0

    assert sorted(c["name"] for c in fake_model.calls) == ["a.mp3", "b.mp4"]
    assert not (library / "notes.srt").exists()
    assert not (library / "sub" / "c.srt").exists()


def test_recursive_includes_sub_folders(run, fake_model, library):
    assert run(library, "-q", "-r") == 0

    assert sorted(c["name"] for c in fake_model.calls) == ["a.mp3", "b.mp4", "c.wav"]
    assert (library / "sub" / "c.srt").exists()


def test_several_inputs_in_any_mix(run, fake_model, library):
    assert run(library / "a.mp3", library / "sub", "-q") == 0

    assert [c["name"] for c in fake_model.calls] == ["a.mp3", "c.wav"]


def test_same_file_given_twice_is_processed_once(run, fake_model, library):
    run(library / "a.mp3", library / "a.mp3", library, "-q")

    assert sorted(c["name"] for c in fake_model.calls) == ["a.mp3", "b.mp4"]


def test_folder_without_media_is_an_error(run, fake_model, tmp_path, caplog):
    (tmp_path / "empty").mkdir()

    assert run(tmp_path / "empty", "-q") == 1
    assert "no media files" in caplog.text
    assert fake_model.loads == 0


def test_output_option_needs_a_single_input(run, fake_model, library):
    with pytest.raises(SystemExit) as exit_info:
        run(library, "-o", "x.srt")

    assert exit_info.value.code == 2


# --- the model is loaded once ----------------------------------------------


def test_model_is_loaded_once_for_the_whole_batch(run, fake_model, library):
    run(library, "-q", "-r")

    assert fake_model.loads == 1
    assert len(fake_model.calls) == 3


# --- skipping ---------------------------------------------------------------


def test_skip_existing_leaves_finished_files_alone(run, fake_model, library):
    (library / "a.srt").write_text("keep me")

    assert run(library, "-q", "--skip-existing") == 0

    assert (library / "a.srt").read_text() == "keep me"
    assert [c["name"] for c in fake_model.calls] == ["b.mp4"]


def test_without_skip_existing_outputs_are_overwritten(run, fake_model, library):
    (library / "a.srt").write_text("old")

    run(library / "a.mp3", "-q")

    assert (library / "a.srt").read_text() != "old"


def test_a_file_is_only_skipped_when_every_format_exists(run, fake_model, library):
    (library / "a.srt").write_text("keep me")

    run(library / "a.mp3", "-q", "-f", "srt,vtt", "--skip-existing")

    assert [c["name"] for c in fake_model.calls] == ["a.mp3"]
    assert (library / "a.vtt").exists()


def test_nothing_to_do_does_not_load_the_model(run, fake_model, library):
    (library / "a.srt").write_text("x")
    (library / "b.srt").write_text("x")

    assert run(library, "-q", "--skip-existing") == 0

    assert fake_model.loads == 0


# --- output folder ----------------------------------------------------------


def test_output_dir_is_created_and_used(run, fake_model, library, tmp_path):
    out = tmp_path / "subs" / "here"

    assert run(library, "-q", "--output-dir", out, "-f", "srt,txt") == 0

    assert names(out) == ["a.srt", "a.txt", "b.srt", "b.txt"]
    assert not (library / "a.srt").exists()


def test_two_inputs_with_the_same_output_name_are_refused(run, fake_model, library, tmp_path):
    (library / "sub" / "a.wav").write_bytes(b"")

    with pytest.raises(SystemExit) as exit_info:
        run(library, "-q", "-r", "--output-dir", tmp_path / "out")

    assert exit_info.value.code == 2
    assert fake_model.calls == []


# --- failures don't stop the batch -----------------------------------------


@pytest.mark.parametrize("error", [RuntimeError("boom"), ValueError("not audio")])
def test_one_bad_file_does_not_stop_the_others(run, fake_model, library, caplog, error):
    fake_model.fail["a.mp3"] = error

    assert run(library, "-q") == 1

    assert (library / "b.srt").exists()
    assert not (library / "a.srt").exists()
    assert "a.mp3" in caplog.text


def test_missing_input_is_reported_and_the_rest_still_run(run, fake_model, library, caplog):
    assert run(library / "nope.mp3", library / "a.mp3", "-q") == 1

    assert "does not exist" in caplog.text
    assert (library / "a.srt").exists()


def test_unwritable_output_fails_that_file_only(run, fake_model, library, tmp_path, caplog):
    blocker = tmp_path / "out"
    blocker.write_text("a file, not a folder")

    assert run(library / "a.mp3", "-q", "--output-dir", blocker) == 1
    assert "couldn't" in caplog.text


def test_a_run_with_failures_does_not_claim_success(run, fake_model, library, caplog):
    fake_model.fail["a.mp3"] = RuntimeError("boom")

    run(library, "--skip-existing")

    assert "1 failed" in caplog.text
    assert "Done!" not in caplog.text


# --- output must never be an input -------------------------------------------


def test_output_may_not_overwrite_the_input(run, fake_model, library):
    video = library / "b.mp4"
    video.write_bytes(b"precious")

    with pytest.raises(SystemExit) as exit_info:
        run(video, "-q", "-o", video)

    assert exit_info.value.code == 2
    assert video.read_bytes() == b"precious"
    assert fake_model.calls == []


def test_output_may_not_overwrite_another_input_via_a_different_spelling(run, fake_model, library):
    notes = library / "notes.txt"
    notes.write_bytes(b"mine")

    with pytest.raises(SystemExit) as exit_info:
        run(library / "a.mp3", notes, "-q", "-f", "txt", "-d", library / "sub" / "..")

    assert exit_info.value.code == 2
    assert notes.read_bytes() == b"mine"


def test_verbose_shows_the_traceback_of_a_failed_file(run, fake_model, library, capsys):
    fake_model.fail["a.mp3"] = RuntimeError("boom")

    assert run(library / "a.mp3", "-v") == 1

    err = capsys.readouterr().err

    assert "Traceback" in err
    assert "RuntimeError: boom" in err


def test_without_verbose_there_is_no_traceback(run, fake_model, library, capsys):
    fake_model.fail["a.mp3"] = RuntimeError("boom")

    assert run(library / "a.mp3") == 1

    err = capsys.readouterr().err

    assert "failed to process" in err
    assert "Traceback" not in err


def test_a_language_list_is_logged_as_not_limiting_detection(run, fake_model, library, capsys):
    assert run(library / "a.mp3", "-l", "he,en") == 0

    err = capsys.readouterr().err

    assert "auto-detect per segment" in err
    assert "not limited" in err
    assert fake_model.calls[0]["language"] is None


def test_ctrl_c_stops_quietly_with_exit_code_130(run, fake_model, library, capsys):
    fake_model.fail["a.mp3"] = KeyboardInterrupt()

    assert run(library, "-q") == 130

    err = capsys.readouterr().err

    assert "interrupted" in err
    assert "Traceback" not in err
    # the batch stops: b.mp4 is not processed and nothing is half-written
    assert not (library / "b.srt").exists()
    assert not (library / "a.srt").exists()


def test_the_load_gets_the_settings_as_the_user_gave_them(run, fake_model, library):
    assert run(library / "a.mp3", "-q", "--model", "tiny") == 0

    assert fake_model.requested.name == "tiny"
    assert fake_model.requested.device == "auto"
    assert fake_model.requested.compute_type == "auto"


def test_macos_resource_fork_files_are_not_picked_up(run, fake_model, library):
    (library / "._a.mp3").write_bytes(b"")

    assert run(library, "-q") == 0

    assert sorted(c["name"] for c in fake_model.calls) == ["a.mp3", "b.mp4"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_an_unreadable_folder_is_an_error_and_the_rest_still_run(
    run, fake_model, library, tmp_path, capsys
):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)

    try:
        assert run(locked, library / "a.mp3", "-q") == 1

    finally:
        locked.chmod(0o700)

    err = capsys.readouterr().err

    assert "couldn't read folder" in err
    assert "Traceback" not in err
    assert (library / "a.srt").exists()
