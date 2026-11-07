"""The whole command, with a fake model standing in for Whisper."""

from types import SimpleNamespace

import pytest

from subtitlemaker import transcribe
from subtitlemaker.cli import main
from tests.conftest import make_segment, make_word


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, path, **kwargs):
        self.calls.append(kwargs)
        words = [make_word(" Hello", 1.0, 1.5), make_word(" world.", 1.6, 2.4)]
        segments = [
            make_segment(" Hello world.", 0.0, 3.0, words if kwargs["word_timestamps"] else None)
        ]
        return iter(segments), SimpleNamespace(language="en", language_probability=0.99)


@pytest.fixture
def fake_model(monkeypatch):
    model = FakeModel()

    def fake_load_model(config, allow_cpu_fallback=False):
        return model, config

    monkeypatch.setattr(transcribe, "load_model", fake_load_model)
    monkeypatch.setattr(transcribe, "cuda_available", lambda: False)

    return model


def run(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["subtitlemaker", *args])
    return main()


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "talk.mp3"
    path.write_bytes(b"")  # never decoded: the model is fake
    return path


def test_cue_follows_the_words_not_the_padded_segment(monkeypatch, fake_model, media):
    assert run(monkeypatch, str(media), "-q") == 0

    srt = (media.with_suffix(".srt")).read_text(encoding="utf-8")
    assert srt == "1\n00:00:01,000 --> 00:00:02,400\nHello world.\n\n"


def test_word_timestamps_are_requested_by_default(monkeypatch, fake_model, media):
    run(monkeypatch, str(media), "-q")

    assert fake_model.calls[0]["word_timestamps"] is True


def test_no_word_timestamps_flag_falls_back_to_segment_timing(monkeypatch, fake_model, media):
    run(monkeypatch, str(media), "-q", "--no-word-timestamps")

    assert fake_model.calls[0]["word_timestamps"] is False
    assert media.with_suffix(".srt").read_text().startswith("1\n00:00:00,000 --> 00:00:03,000")


def test_config_file_can_turn_word_timestamps_off(monkeypatch, fake_model, media, tmp_path):
    config = tmp_path / "c.toml"
    config.write_text("[model]\nword_timestamps = false\n")

    run(monkeypatch, str(media), "-q", "--config", str(config))

    assert fake_model.calls[0]["word_timestamps"] is False


def test_output_option_and_style_flags_are_applied(monkeypatch, fake_model, media, tmp_path):
    out = tmp_path / "custom.srt"

    assert run(monkeypatch, str(media), "-q", "-o", str(out), "--min-duration", "2") == 0

    assert "00:00:01,000 --> 00:00:03,000" in out.read_text()


def test_unwritable_output_is_reported(monkeypatch, fake_model, media, tmp_path, caplog):
    assert run(monkeypatch, str(media), "-q", "-o", str(tmp_path / "no" / "dir.srt")) == 1
    assert "couldn't write" in caplog.text
