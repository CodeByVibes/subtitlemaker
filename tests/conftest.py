"""Shared test helpers."""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from subtitlemaker import transcribe
from subtitlemaker.log import LOGGER_NAME

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def make_segment(text, start, end, words=None):
    """A stand-in for a faster-whisper Segment."""

    return SimpleNamespace(text=text, start=start, end=end, words=words)


def make_word(word, start, end):
    """A stand-in for a faster-whisper Word (Whisper puts a space before each word)."""

    return SimpleNamespace(word=word, start=start, end=end, probability=1.0)


@pytest.fixture(autouse=True)
def _reset_package_log_level():
    """`setup_logging(quiet=True)` leaves the package logger at WARNING for the whole session,
    which would hide INFO records from `caplog` in whatever test runs next."""

    yield

    logging.getLogger(LOGGER_NAME).setLevel(logging.NOTSET)


@pytest.fixture
def segment():
    return make_segment


@pytest.fixture
def word():
    return make_word


class FakeModel:
    """Stands in for a Whisper model: records calls, can be told to fail."""

    def __init__(self):
        self.calls = []
        self.fail = {}  # file name -> exception to raise
        self.segments = None  # segments to return instead of the default
        self.language = "en"  # the language it "detects"
        self.audio_duration = None  # seconds of decoded audio to report in `info`, if any

    def transcribe(self, path, **kwargs):
        name = Path(path).name
        self.calls.append({"name": name, **kwargs})

        if name in self.fail:
            raise self.fail[name]

        if self.segments is not None:
            return iter(self.segments), self._info()

        words = [make_word(" Hello", 1.0, 1.5), make_word(" world.", 1.6, 2.4)]
        words = words if kwargs["word_timestamps"] else None
        segments = [make_segment(" Hello world.", 0.0, 3.0, words)]

        return iter(segments), self._info()

    def _info(self):
        info = SimpleNamespace(language=self.language, language_probability=0.99)

        if self.audio_duration is not None:
            info.duration = self.audio_duration

        return info


@pytest.fixture
def fake_model(monkeypatch):
    """A fake model, installed in place of the real loader."""

    model = FakeModel()
    model.loads = 0

    def fake_load_model(config, allow_cpu_fallback=False, requested=None, on_download=None):
        model.loads += 1
        model.requested = requested
        return model, config

    monkeypatch.setattr(transcribe, "load_model", fake_load_model)
    monkeypatch.setattr(transcribe, "cuda_available", lambda: False)

    return model


@pytest.fixture
def run(monkeypatch):
    """Run the command line: `run("file.mp3", "-q")` returns the exit code."""

    from subtitlemaker.cli import main

    def _run(*args):
        monkeypatch.setattr("sys.argv", ["subtitlemaker", *map(str, args)])
        return main()

    return _run
