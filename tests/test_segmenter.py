import random

import pytest

from subtitlemaker.config import SubtitleStyle
from subtitlemaker.segmenter import build_subtitles
from tests.conftest import make_segment

STYLE = SubtitleStyle()
EPS = 1e-9


def plain(cue):
    return cue["text"].replace("\n", " ")


def test_one_short_segment_gives_one_cue(segment):
    cues = build_subtitles([segment(" Hello there. ", 1.0, 3.0)], STYLE)

    assert len(cues) == 1
    assert cues[0]["text"] == "Hello there."
    assert cues[0]["start"] == pytest.approx(1.0, abs=0.1)


def test_empty_and_whitespace_segments_are_skipped(segment):
    cues = build_subtitles(
        [segment("", 0, 1), segment("   ", 1, 2), segment("Real text.", 2, 4)], STYLE
    )

    assert [plain(c) for c in cues] == ["Real text."]


def test_no_segments_gives_no_cues():
    assert build_subtitles([], STYLE) == []


def test_long_segment_is_split_without_losing_words(segment):
    text = " ".join(f"word{i}" for i in range(60))  # far more than 84 characters

    cues = build_subtitles([segment(text, 0, 20)], STYLE)

    assert len(cues) > 1
    assert " ".join(plain(c) for c in cues) == text


def test_cues_respect_line_and_length_limits(segment):
    text = "the quick brown fox jumps over the lazy dog " * 8

    cues = build_subtitles([segment(text, 0, 30)], STYLE)

    for cue in cues:
        lines = cue["text"].split("\n")
        assert len(lines) <= STYLE.max_lines
        assert all(len(line) <= STYLE.max_line_length for line in lines)


def test_style_changes_the_layout(segment):
    text = "the quick brown fox jumps over the lazy dog " * 4
    narrow = SubtitleStyle(max_line_length=20, max_lines=1)

    wide_cues = build_subtitles([segment(text, 0, 20)], STYLE)
    narrow_cues = build_subtitles([segment(text, 0, 20)], narrow)

    assert len(narrow_cues) > len(wide_cues)
    assert all("\n" not in c["text"] for c in narrow_cues)
    assert all(len(c["text"]) <= 20 for c in narrow_cues)


def _random_segments(seed, count=300):
    rng = random.Random(seed)
    words = "the quick brown fox jumps over a lazy dog, however; incredible! why?".split()
    segments, clock = [], 0.0
    for _ in range(count):
        start = clock + rng.random() * 3
        end = start + rng.random() * rng.choice([0.2, 2, 10])
        text = " ".join(rng.choice(words) for _ in range(rng.choice([0, 1, 3, 8, 20, 45, 90])))
        segments.append(make_segment(text, start, end))
        clock = start + rng.random() * 4 - 0.5  # segments may overlap
    return segments


@pytest.mark.parametrize("seed", range(5))
def test_cues_are_ordered_and_never_overlap(seed):
    cues = build_subtitles(_random_segments(seed), STYLE)

    assert cues
    for cue in cues:
        assert cue["end"] > cue["start"]
    for previous, current in zip(cues, cues[1:], strict=False):
        assert current["start"] >= previous["end"] + STYLE.min_gap - EPS


@pytest.mark.parametrize("seed", range(5))
def test_no_words_are_lost_or_invented(seed):
    segments = _random_segments(seed)

    cues = build_subtitles(segments, STYLE)

    expected = " ".join(" ".join(s.text.split()) for s in segments if s.text.split()).split()
    actual = " ".join(plain(c) for c in cues).split()
    assert actual == expected
