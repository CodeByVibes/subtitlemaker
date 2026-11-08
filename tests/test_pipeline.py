"""The whole command, with a fake model standing in for Whisper."""

import pytest

from tests.conftest import make_segment, make_word


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "talk.mp3"
    path.write_bytes(b"")  # never decoded: the model is fake
    return path


def test_cue_follows_the_words_not_the_padded_segment(run, fake_model, media):
    assert run(str(media), "-q", "--linger", "0") == 0  # speech timing only

    srt = (media.with_suffix(".srt")).read_text(encoding="utf-8")
    assert srt == "1\n00:00:01,000 --> 00:00:02,400\nHello world.\n\n"


def test_word_timestamps_are_requested_by_default(run, fake_model, media):
    run(str(media), "-q")

    assert fake_model.calls[0]["word_timestamps"] is True


def test_no_word_timestamps_flag_falls_back_to_segment_timing(run, fake_model, media):
    run(str(media), "-q", "--no-word-timestamps", "--linger", "0")

    assert fake_model.calls[0]["word_timestamps"] is False
    assert media.with_suffix(".srt").read_text().startswith("1\n00:00:00,000 --> 00:00:03,000")


def test_config_file_can_turn_word_timestamps_off(run, fake_model, media, tmp_path):
    config = tmp_path / "c.toml"
    config.write_text("[model]\nword_timestamps = false\n")

    run(str(media), "-q", "--config", str(config))

    assert fake_model.calls[0]["word_timestamps"] is False


def test_output_option_and_style_flags_are_applied(run, fake_model, media, tmp_path):
    out = tmp_path / "custom.srt"

    assert run(str(media), "-q", "-o", str(out), "--min-duration", "2") == 0

    assert "00:00:01,000 --> 00:00:03,000" in out.read_text()


def test_unwritable_output_is_reported(run, fake_model, media, tmp_path, caplog):
    assert run(str(media), "-q", "-o", str(tmp_path / "no" / "dir.srt")) == 1
    assert "couldn't write" in caplog.text


def test_default_task_keeps_the_spoken_language(run, fake_model, media):
    run(media, "-q")

    assert fake_model.calls[0]["task"] == "transcribe"


def test_translate_task_is_opt_in(run, fake_model, media):
    run(media, "-q", "-t", "translate")

    assert fake_model.calls[0]["task"] == "translate"


def test_version_flag(run, capsys):
    with pytest.raises(SystemExit) as exit_info:
        run("--version")

    assert exit_info.value.code == 0
    from subtitlemaker import __version__

    assert capsys.readouterr().out.strip() == f"subtitlemaker {__version__}"


def _pause_segment():
    words = [
        make_word(" first", 0.0, 0.5),
        make_word(" words", 0.6, 1.0),
        make_word(" later", 9.0, 9.4),
        make_word(" words", 9.5, 10.0),
    ]
    return make_segment(" first words later words", 0.0, 10.0, words)


def test_max_pause_flag_changes_the_split(run, fake_model, media):
    fake_model.segments = [_pause_segment()]

    run(media, "-q")
    assert media.with_suffix(".srt").read_text().count("-->") == 2

    run(media, "-q", "--max-pause", "20")
    assert media.with_suffix(".srt").read_text().count("-->") == 1


def test_max_pause_can_be_set_in_the_config_file(run, fake_model, media, tmp_path):
    fake_model.segments = [_pause_segment()]
    config = tmp_path / "c.toml"
    config.write_text("[style]\nmax_pause = 20\n")

    run(media, "-q", "--config", config)

    assert media.with_suffix(".srt").read_text().count("-->") == 1


def test_invalid_max_pause_is_a_usage_error(run, fake_model, media):
    with pytest.raises(SystemExit) as exit_info:
        run(media, "--max-pause", "0")

    assert exit_info.value.code == 2


def test_linger_can_be_set_in_the_config_file(run, fake_model, media, tmp_path):
    config = tmp_path / "c.toml"
    config.write_text("[style]\nlinger = 0.2\n")

    run(media, "-q", "--config", config)

    assert "00:00:01,000 --> 00:00:02,600" in media.with_suffix(".srt").read_text()


def test_linger_flag_overrides_the_default(run, fake_model, media):
    run(media, "-q", "--linger", "1")

    assert "00:00:01,000 --> 00:00:03,400" in media.with_suffix(".srt").read_text()


@pytest.mark.parametrize("flag", ["--linger", "--close-gap"])
def test_negative_linger_or_close_gap_is_a_usage_error(run, fake_model, media, flag):
    with pytest.raises(SystemExit) as exit_info:
        run(media, flag, "-1")

    assert exit_info.value.code == 2


def _either_or(fake_model):
    text = "Either you work for the system or you make the system work for you."
    words = [make_word(" " + w, i * 0.3, i * 0.3 + 0.25) for i, w in enumerate(text.split())]
    fake_model.segments = [make_segment(" " + text, 0.0, 5.0, words)]


@pytest.mark.parametrize(
    ("language", "extra", "line_one"),
    [
        ("en", [], "Either you work for the system\n"),  # English list: not "or" last
        ("sv", [], "Either you work for the system or\n"),  # Swedish list has no "or"
        ("sv", ["-t", "translate"], "Either you work for the system\n"),  # output is English
        ("en", ["-m"], "Either you work for the system or\n"),  # mixed: no list
    ],
)
def test_line_breaks_use_the_language_of_the_subtitles(
    run, fake_model, media, language, extra, line_one
):
    _either_or(fake_model)
    fake_model.language = language

    run(media, "-q", *extra)

    assert line_one in media.with_suffix(".srt").read_text()
