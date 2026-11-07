"""Runs a real Whisper model. Slow, and downloads the tiny model on first use.

uv run pytest -m integration
"""

import re

import pytest

from subtitlemaker.cli import main
from tests.conftest import FIXTURES_DIR

pytestmark = pytest.mark.integration

SAMPLE = FIXTURES_DIR / "jfk.flac"  # public domain: US government work, 1961
TIME = r"(\d\d):(\d\d):(\d\d),(\d{3})"


def seconds(match, offset=0):
    h, m, s, ms = (int(match.group(offset + i)) for i in range(1, 5))
    return h * 3600 + m * 60 + s + ms / 1000


def read_cues(path):
    cues = []

    for block in path.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.split("\n")
        match = re.fullmatch(f"{TIME} --> {TIME}", lines[1])
        assert match, f"bad timing line: {lines[1]!r}"
        cues.append((seconds(match), seconds(match, 4), " ".join(lines[2:])))

    return cues


@pytest.mark.parametrize("word_timestamps", [True, False])
def test_transcribes_the_sample_end_to_end(monkeypatch, tmp_path, word_timestamps):
    out = tmp_path / "jfk.srt"
    args = [str(SAMPLE), "-o", str(out), "-l", "en", "-t", "transcribe", "-q"]
    args += ["--model", "tiny", "--device", "cpu"]
    args += ["--word-timestamps" if word_timestamps else "--no-word-timestamps"]
    monkeypatch.setattr("sys.argv", ["subtitlemaker", *args])

    assert main() == 0

    cues = read_cues(out)
    text = " ".join(t for *_, t in cues).lower()

    assert "ask not what your country can do for you" in text
    assert all(end > start for start, end, _ in cues)
    assert all(b[0] >= a[1] for a, b in zip(cues, cues[1:], strict=False))
    assert cues[-1][1] <= 11.5  # the clip is 11 seconds long


def test_first_cue_starts_at_the_first_word(monkeypatch, tmp_path):
    # The recording starts straight on "And so, my fellow Americans", with no lead-in.
    out = tmp_path / "jfk.srt"
    argv = [str(SAMPLE), "-o", str(out), "-l", "en", "-t", "transcribe", "-q"]
    argv += ["--model", "tiny", "--device", "cpu"]
    monkeypatch.setattr("sys.argv", ["subtitlemaker", *argv])

    assert main() == 0

    assert read_cues(out)[0][0] < 0.5
