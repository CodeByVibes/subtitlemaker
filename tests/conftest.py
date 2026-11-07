"""Shared test helpers."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from subtitlemaker import transcribe

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def make_segment(text, start, end, words=None):
    """A stand-in for a faster-whisper Segment."""

    return SimpleNamespace(text=text, start=start, end=end, words=words)


def make_word(word, start, end):
    """A stand-in for a faster-whisper Word (Whisper puts a space before each word)."""

    return SimpleNamespace(word=word, start=start, end=end, probability=1.0)


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

    def transcribe(self, path, **kwargs):
        name = Path(path).name
        self.calls.append({"name": name, **kwargs})

        if name in self.fail:
            raise self.fail[name]

        if self.segments is not None:
            return iter(self.segments), SimpleNamespace(language="en", language_probability=0.99)

        words = [make_word(" Hello", 1.0, 1.5), make_word(" world.", 1.6, 2.4)]
        words = words if kwargs["word_timestamps"] else None
        segments = [make_segment(" Hello world.", 0.0, 3.0, words)]

        return iter(segments), SimpleNamespace(language="en", language_probability=0.99)


@pytest.fixture
def fake_model(monkeypatch):
    """A fake model, installed in place of the real loader."""

    model = FakeModel()
    model.loads = 0

    def fake_load_model(config, allow_cpu_fallback=False):
        model.loads += 1
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
