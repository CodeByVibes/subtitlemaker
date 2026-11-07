"""Long silences inside one Whisper segment must not end up inside one cue.

Whisper sometimes joins words that are far apart (a laugh track or music in
between) into one segment. Grouping them by length alone showed the later
words many seconds before they were spoken.
"""

import pytest

from subtitlemaker.config import ConfigError, SubtitleStyle
from subtitlemaker.segmenter import build_subtitles
from tests.conftest import make_segment, make_word

STYLE = SubtitleStyle()


def spoken(text, start, step=0.3):
    """`(word, start, end)` for each word of `text`, evenly spaced from `start`."""

    return [
        (w, round(start + i * step, 3), round(start + i * step + step * 0.8, 3))
        for i, w in enumerate(text.split())
    ]


def segment_of(*parts):
    words = [make_word(" " + w, s, e) for part in parts for w, s, e in part]
    return make_segment("".join(w.word for w in words), words[0].start, words[-1].end, words)


def test_real_case_words_twelve_seconds_apart_become_two_cues():
    # Word times from a real large-v3 run on a sitcom clip: the first words
    # end at 2.5s, "tom petty ..." is spoken from 14.8s.
    first = spoken("he killed a nun when she misplaced his lunch uh", 0.0, 0.25)
    second = spoken("tom petty tickets are moving", 14.8, 0.35)

    cues = build_subtitles([segment_of(first, second)], STYLE)

    assert [c["text"].replace("\n", " ") for c in cues] == [
        "he killed a nun when she misplaced his lunch uh",
        "tom petty tickets are moving",
    ]
    assert cues[0]["start"] == 0.0
    assert cues[1]["start"] == 14.8  # shown when it is spoken, not 14 seconds before


def test_the_first_cue_does_not_run_on_into_the_silence():
    first = spoken("hello there", 0.0)
    second = spoken("anyone home", 20.0)

    cues = build_subtitles([segment_of(first, second)], STYLE)

    assert cues[0]["end"] < 5  # padding to the minimum duration, nowhere near 20s


def test_a_short_pause_does_not_split():
    cues = build_subtitles(
        [segment_of(spoken("one two three", 0.0), spoken("four five six", 1.7))], STYLE
    )  # 0.86s gap between "three" and "four"

    assert len(cues) == 1


def test_a_pause_of_exactly_the_limit_splits():
    first = [("one", 0.0, 0.5)]
    second = [("two", 1.5, 2.0)]  # gap of exactly 1.0s

    assert len(build_subtitles([segment_of(first, second)], STYLE)) == 2


def test_just_under_the_limit_does_not_split():
    first = [("one", 0.0, 0.5)]
    second = [("two", 1.49, 2.0)]

    assert len(build_subtitles([segment_of(first, second)], STYLE)) == 1


def test_the_limit_is_configurable():
    gap = [segment_of(spoken("one two", 0.0), spoken("three four", 3.5))]  # 2.9s gap

    assert len(build_subtitles(gap, SubtitleStyle(max_pause=5.0))) == 1
    assert len(build_subtitles(gap, SubtitleStyle(max_pause=2.0))) == 2


def test_several_pauses_make_several_cues():
    parts = [spoken("a b", 0.0), spoken("c d", 10.0), spoken("e f", 20.0)]

    cues = build_subtitles([segment_of(*parts)], STYLE)

    assert [c["start"] for c in cues] == [0.0, 10.0, 20.0]


def test_every_word_is_kept_when_splitting_at_pauses():
    parts = [spoken("alpha bravo charlie", 0.0), spoken("delta echo foxtrot", 9.0)]

    cues = build_subtitles([segment_of(*parts)], STYLE)

    words = " ".join(c["text"].replace("\n", " ") for c in cues).split()
    assert words == "alpha bravo charlie delta echo foxtrot".split()


def test_pauses_combine_with_the_length_limit():
    # A long run of words, a pause, then another long run: both halves still
    # have to respect the line limits.
    long_text = "the quick brown fox jumps over the lazy dog " * 3
    parts = [spoken(long_text, 0.0, 0.2), spoken(long_text, 60.0, 0.2)]

    cues = build_subtitles([segment_of(*parts)], STYLE)

    assert any(c["start"] == 60.0 for c in cues)
    for cue in cues:
        assert all(len(line) <= STYLE.max_line_length for line in cue["text"].split("\n"))
    assert max(c["end"] for c in cues if c["start"] < 60) < 30


def test_a_segment_without_word_timing_is_unchanged():
    # No words, so there is nothing to measure a pause with: segment timing as before.
    segment = make_segment("one two three four five six", 0.0, 30.0, None)

    assert len(build_subtitles([segment], STYLE)) == 1


def test_default_is_one_second():
    assert SubtitleStyle().max_pause == 1.0


@pytest.mark.parametrize("value", [0, -1, -0.5])
def test_max_pause_must_be_positive(value):
    with pytest.raises(ConfigError, match="max_pause"):
        SubtitleStyle(max_pause=value)
