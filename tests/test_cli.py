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
