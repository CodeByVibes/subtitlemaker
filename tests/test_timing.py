"""Cue timing rules.

Speech timing is authoritative: readability padding (minimum duration,
reading speed) may extend a cue's end into free space, but never delays the
next cue, and a cue never starts later than the speech it shows.
"""

import pytest

from subtitlemaker.config import ConfigError, SubtitleStyle
from subtitlemaker.segmenter import build_subtitles
from tests.conftest import make_segment

STYLE = SubtitleStyle()
EPS = 1e-6


def spans(cues):
    return [(round(c["start"], 3), round(c["end"], 3)) for c in cues]


def test_first_cue_starts_exactly_when_speech_starts(segment):
    cues = build_subtitles([segment("Hello there.", 0.0, 2.0)], STYLE)

    assert cues[0]["start"] == 0.0


def test_stretched_cue_does_not_delay_the_next_one(segment):
    # "Yes." is 0.3s long but must be shown for 1s; the next line is spoken at 0.8s.
    cues = build_subtitles(
        [segment("Yes.", 0.0, 0.3), segment("I really think so.", 0.8, 2.5)], STYLE
    )

    assert cues[1]["start"] == 0.8
    assert cues[0]["end"] <= 0.8 - STYLE.min_gap + EPS


def test_cue_is_never_extended_into_following_speech(segment):
    cues = build_subtitles(
        [segment("Okay.", 10.0, 10.4), segment("Let us begin the meeting now.", 10.9, 13.0)],
        STYLE,
    )

    assert cues[1]["start"] == 10.9
    assert cues[0]["end"] == pytest.approx(10.9 - STYLE.min_gap)


def test_short_cue_is_extended_to_minimum_duration_when_there_is_room(segment):
    cues = build_subtitles([segment("Yes.", 5.0, 5.3), segment("Later.", 20.0, 21.0)], STYLE)

    assert cues[0]["end"] - cues[0]["start"] == pytest.approx(STYLE.min_duration)


def test_cue_is_extended_to_reading_speed_when_there_is_room(segment):
    text = "x" * 40 + " " + "y" * 39  # 80 characters, needs 4s at 20 cps
    cues = build_subtitles([segment(text, 0.0, 1.5), segment("Later.", 30.0, 31.0)], STYLE)

    assert cues[0]["end"] - cues[0]["start"] == pytest.approx(4.0)


def test_speech_end_plus_linger_is_kept_when_longer_than_needed(segment):
    cues = build_subtitles([segment("Hello.", 0.0, 3.5)], STYLE)

    assert cues[0]["end"] == pytest.approx(3.5 + STYLE.linger)


def test_max_duration_is_a_hard_cap(segment):
    style = SubtitleStyle(max_cps=8, max_duration=5)
    cues = build_subtitles([segment("x " * 40, 0.0, 2.0)], style)

    assert all(c["end"] - c["start"] <= 5 + EPS for c in cues)


def test_max_duration_also_caps_long_speech(segment):
    cues = build_subtitles([segment("Hello.", 0.0, 12.0)], STYLE)

    assert cues[0]["end"] - cues[0]["start"] == pytest.approx(STYLE.max_duration)


def test_min_duration_gives_way_to_the_next_cue(segment):
    # Only 0.4s between the two speech starts: the first cue ends early rather
    # than overlapping or pushing the second one back.
    cues = build_subtitles([segment("A.", 0.0, 0.2), segment("B.", 0.4, 0.6)], STYLE)

    assert cues[1]["start"] == 0.4
    assert 0 < cues[0]["end"] - cues[0]["start"] < STYLE.min_duration
    assert cues[0]["end"] <= 0.4 - STYLE.min_gap + EPS


def test_overlapping_source_segments_never_overlap_in_output(segment):
    cues = build_subtitles([segment("One.", 0.0, 2.0), segment("Two.", 1.0, 3.0)], STYLE)

    assert cues[1]["start"] >= cues[0]["end"] + STYLE.min_gap - EPS
    assert all(c["end"] > c["start"] for c in cues)


def test_speech_start_is_kept_for_well_separated_segments():
    segments = [make_segment(f"Line number {i}.", i * 5.0, i * 5.0 + 1.5) for i in range(20)]

    cues = build_subtitles(segments, STYLE)

    assert [c["start"] for c in cues] == [s.start for s in segments]


def test_long_segment_chunks_always_fit_in_valid_lines(segment):
    # 83 characters: packing to 84 left no word boundary giving two lines <= 42.
    text = "the quick brown fox jumps over the lazy dog " * 8

    cues = build_subtitles([segment(text, 0, 30)], STYLE)

    for cue in cues:
        lines = cue["text"].split("\n")
        assert len(lines) <= STYLE.max_lines
        assert all(len(line) <= STYLE.max_line_length for line in lines)


def test_one_line_style_never_produces_two_lines(segment):
    style = SubtitleStyle(max_lines=1)
    text = "the quick brown fox jumps over the lazy dog " * 3
    cues = build_subtitles([segment(text, 0, 20)], style)

    assert all("\n" not in c["text"] for c in cues)
    assert all(len(c["text"]) <= style.max_line_length for c in cues)


@pytest.mark.parametrize("lines", [0, 3, 4])
def test_only_one_or_two_lines_are_supported(lines):
    with pytest.raises(ConfigError, match="max_lines"):
        SubtitleStyle(max_lines=lines)


def test_a_cue_is_never_shown_for_less_than_a_tenth_of_a_second(segment):
    # The second line is spoken before the first has had any time on screen.
    cues = build_subtitles([segment("One.", 0.0, 1.0), segment("Two.", 0.02, 1.0)], STYLE)

    assert cues[0]["end"] - cues[0]["start"] == pytest.approx(0.1)
    assert cues[1]["start"] == pytest.approx(cues[0]["end"] + STYLE.min_gap)


QUIET = SubtitleStyle(linger=0.0)  # isolates gap closing from the linger


def test_cue_lingers_after_its_speech_when_there_is_room(segment):
    cues = build_subtitles([segment("Hello there friend.", 0.0, 2.0)], STYLE)

    assert cues[0]["end"] == pytest.approx(2.0 + STYLE.linger)


def test_linger_never_delays_or_overlaps_the_next_cue(segment):
    cues = build_subtitles(
        [segment("Hello there friend.", 0.0, 2.0), segment("Hi.", 2.2, 3.0)], STYLE
    )

    assert cues[1]["start"] == 2.2
    assert cues[0]["end"] == pytest.approx(2.2 - STYLE.min_gap)


def test_linger_zero_ends_at_the_speech(segment):
    cues = build_subtitles([segment("Hello there friend.", 0.0, 2.0)], QUIET)

    assert cues[0]["end"] == pytest.approx(2.0)


def test_a_short_gap_is_closed(segment):
    cues = build_subtitles(
        [segment("Hello there friend.", 0.0, 2.0), segment("Hi.", 2.3, 3.0)], QUIET
    )

    assert cues[0]["end"] == pytest.approx(2.3 - QUIET.min_gap)


def test_a_gap_of_close_gap_or_more_stays_open(segment):
    cues = build_subtitles(
        [segment("Hello there friend.", 0.0, 2.0), segment("Hi.", 2.5, 3.0)], QUIET
    )  # exactly 0.5s

    assert cues[0]["end"] == pytest.approx(2.0)


def test_close_gap_zero_turns_it_off(segment):
    style = SubtitleStyle(linger=0.0, close_gap=0.0)
    cues = build_subtitles(
        [segment("Hello there friend.", 0.0, 2.0), segment("Hi.", 2.1, 3.0)], style
    )

    assert cues[0]["end"] == pytest.approx(2.0)


def test_closing_a_gap_respects_max_duration(segment):
    cues = build_subtitles(
        [segment("Hello there friend.", 0.0, 6.9), segment("Hi.", 7.3, 8.0)], QUIET
    )

    assert cues[0]["end"] == pytest.approx(STYLE.max_duration)


@pytest.mark.parametrize("name", ["linger", "close_gap"])
@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf")])
def test_linger_and_close_gap_must_be_finite_and_not_negative(name, value):
    with pytest.raises(ConfigError, match=name):
        SubtitleStyle(**{name: value})
