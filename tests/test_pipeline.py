"""The whole command, with a fake model standing in for Whisper."""

import pytest


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "talk.mp3"
    path.write_bytes(b"")  # never decoded: the model is fake
    return path


def test_cue_follows_the_words_not_the_padded_segment(run, fake_model, media):
    assert run(str(media), "-q") == 0

    srt = (media.with_suffix(".srt")).read_text(encoding="utf-8")
    assert srt == "1\n00:00:01,000 --> 00:00:02,400\nHello world.\n\n"


def test_word_timestamps_are_requested_by_default(run, fake_model, media):
    run(str(media), "-q")

    assert fake_model.calls[0]["word_timestamps"] is True


def test_no_word_timestamps_flag_falls_back_to_segment_timing(run, fake_model, media):
    run(str(media), "-q", "--no-word-timestamps")

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
