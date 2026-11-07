import pytest

from subtitlemaker.cli import main


def run(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["subtitlemaker", *args])
    return main()


def test_missing_input_file_is_reported(monkeypatch, caplog):
    assert run(monkeypatch, "/nonexistent/file.mp4") == 1
    assert "input file does not exist" in caplog.text


def test_bad_config_file_exits_with_usage_error(monkeypatch, tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text("[style]\nnope = 1\n")

    with pytest.raises(SystemExit) as exit_info:
        run(monkeypatch, "x.mp3", "--config", str(bad))

    assert exit_info.value.code == 2
    assert "unknown key" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ["--max-lines", "0"],
        ["--min-duration", "9"],
        ["--language", "zz"],
        ["--device", "tpu"],
        ["--quiet", "--verbose"],
        ["--detect-segments", "0"],
    ],
)
def test_bad_options_exit_with_usage_error(monkeypatch, args):
    with pytest.raises(SystemExit) as exit_info:
        run(monkeypatch, "x.mp3", *args)

    assert exit_info.value.code == 2


def test_unknown_model_is_reported_before_loading(monkeypatch, tmp_path, caplog):
    media = tmp_path / "a.mp3"
    media.write_bytes(b"")

    assert run(monkeypatch, str(media), "--model", "nonsense") == 1
    assert "unknown model" in caplog.text


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_help_and_version_do_not_load_the_machine_learning_libraries(flag):
    import subprocess
    import sys

    code = (
        "import sys\n"
        "from subtitlemaker.cli import main\n"
        f"sys.argv = ['subtitlemaker', '{flag}']\n"
        "try:\n"
        "    main()\n"
        "except SystemExit:\n"
        "    pass\n"
        "heavy = [m for m in ('faster_whisper', 'ctranslate2', 'numpy') if m in sys.modules]\n"
        "print('LOADED', heavy)\n"
    )

    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert "LOADED []" in result.stdout, result.stdout + result.stderr


# --- output planning, without going through argv -------------------------------


def _plan_args(**kwargs):
    from types import SimpleNamespace

    return SimpleNamespace(**{"output": None, "output_dir": None, **kwargs})


def test_planning_puts_outputs_next_to_the_inputs(tmp_path):
    from subtitlemaker.cli import _plan_all_outputs

    plan = _plan_all_outputs([tmp_path / "a.mp3"], _plan_args(), ["srt", "txt"])

    assert plan == {tmp_path / "a.mp3": {"srt": tmp_path / "a.srt", "txt": tmp_path / "a.txt"}}


def test_planning_refuses_an_output_that_is_an_input(tmp_path):
    from subtitlemaker.cli import _plan_all_outputs

    media = tmp_path / "talk.mp4"
    media.write_bytes(b"")

    with pytest.raises(ValueError, match="would be overwritten"):
        _plan_all_outputs([media], _plan_args(output=str(media)), ["srt"])


def test_planning_refuses_two_inputs_with_one_output(tmp_path):
    from subtitlemaker.cli import _plan_all_outputs

    files = [tmp_path / "x" / "a.mp3", tmp_path / "y" / "a.mp3"]

    with pytest.raises(ValueError, match="would both write"):
        _plan_all_outputs(files, _plan_args(output_dir=str(tmp_path / "out")), ["srt"])


def test_planning_refuses_output_for_several_inputs(tmp_path):
    from subtitlemaker.cli import _plan_all_outputs

    with pytest.raises(ValueError, match="single input"):
        _plan_all_outputs(
            [tmp_path / "a.mp3", tmp_path / "b.mp3"], _plan_args(output="x.srt"), ["srt"]
        )
