"""Shared test helpers."""

from types import SimpleNamespace

import pytest


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
