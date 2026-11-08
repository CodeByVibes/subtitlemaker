"""Cue splitting and timing from word timestamps."""

import pytest

from subtitlemaker.config import ModelConfig, SubtitleStyle
from subtitlemaker.segmenter import build_subtitles
from tests.conftest import make_segment, make_word

STYLE = SubtitleStyle()


def words_segment(spec, start=None, end=None):
    """`spec` is [(word, start, end), ...]; Whisper puts a space before each word."""

    words = [make_word(w if w.startswith(("-", ",", ".")) else " " + w, s, e) for w, s, e in spec]
    text = "".join(w.word for w in words)

    return make_segment(
        text,
        spec[0][1] if start is None else start,
        spec[-1][2] if end is None else end,
        words,
    )


def evenly(text, start, step=0.4):
    """Timings for every word of `text`, one every `step` seconds."""

    return [
        (w, start + i * step, start + i * step + step * 0.9) for i, w in enumerate(text.split())
    ]


def test_cue_runs_from_first_to_last_word_not_the_padded_segment():
    # The segment includes 1s of silence either side; the words say when speech happens.
    segment = words_segment(
        [("Hello", 1.0, 1.4), ("there", 1.5, 2.2), ("friend.", 2.3, 3.0)], start=0.0, end=4.0
    )

    cues = build_subtitles([segment], STYLE)

    assert len(cues) == 1
    assert cues[0]["start"] == 1.0
    assert cues[0]["end"] == pytest.approx(3.0)


def test_split_points_use_real_word_times_not_character_counts():
    # 20 slow words, then 20 fast ones: proportional-by-characters would put the
    # second cue's start far from where its first word is actually spoken.
    slow = evenly(
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima", 0.0, 1.0
    )
    fast = evenly("mike november oscar papa quebec romeo sierra tango uniform victor", 12.5, 0.1)
    segment = words_segment(slow + fast)

    cues = build_subtitles([segment], STYLE)

    assert len(cues) >= 2
    starts = {w: s for w, s, _ in slow + fast}
    for cue in cues:
        first_word = cue["text"].split()[0]
        assert cue["start"] == pytest.approx(starts[first_word])


def test_every_word_is_kept_in_order():
    text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen " * 2
    segment = words_segment(evenly(text, 0.0, 0.3))

    cues = build_subtitles([segment], STYLE)

    assert " ".join(c["text"].replace("\n", " ") for c in cues).split() == text.split()


def test_breaks_at_sentence_end_when_a_cue_has_to_be_split():
    # One short sentence, then a long one: too long for one cue, so break after "Right."
    text = (
        "Right. and then we went over to the other side of the river and walked on for a long time"
    )
    cues = build_subtitles([words_segment(evenly(text, 0))], STYLE)

    assert len(cues) == 2
    assert cues[0]["text"] == "Right."


def test_breaks_at_the_last_sentence_end_that_fits():
    text = "First. Second one is here. and then we went over to the other side of the river and on"
    cues = build_subtitles([words_segment(evenly(text, 0))], STYLE)

    assert cues[0]["text"] == "First. Second one is here."


def test_cues_never_exceed_line_limits_with_words():
    text = "the quick brown fox jumps over the lazy dog " * 8
    cues = build_subtitles([words_segment(evenly(text, 0.0, 0.25))], STYLE)

    for cue in cues:
        lines = cue["text"].split("\n")
        assert len(lines) <= STYLE.max_lines
        assert all(len(line) <= STYLE.max_line_length for line in lines)


@pytest.mark.parametrize("words", [None, []])
def test_segments_without_words_use_segment_timing(words):
    segment = make_segment("Hello there.", 2.0, 4.0, words)

    cues = build_subtitles([segment], STYLE)

    assert cues[0]["start"] == 2.0
    assert cues[0]["end"] == pytest.approx(4.0)


def test_words_that_disagree_with_the_text_are_ignored():
    segment = make_segment(
        " The real text.",
        0.0,
        3.0,
        [make_word(" something", 5.0, 6.0), make_word(" else", 6.0, 7.0)],
    )

    cues = build_subtitles([segment], STYLE)

    assert cues[0]["text"] == "The real text."
    assert cues[0]["start"] == 0.0


def test_words_without_times_are_ignored():
    segment = make_segment(
        " Hello there.",
        1.0,
        3.0,
        [make_word(" Hello", None, None), make_word(" there.", None, None)],
    )

    cues = build_subtitles([segment], STYLE)

    assert cues[0]["text"] == "Hello there."
    assert cues[0]["start"] == 1.0


def test_blank_words_are_skipped_and_punctuation_is_tidied():
    segment = make_segment(
        " Hello , world !",
        0.0,
        2.0,
        [
            make_word(" Hello", 0.0, 0.5),
            make_word(" ", 0.5, 0.6),
            make_word(" ,", 0.6, 0.7),
            make_word(" world", 0.8, 1.2),
            make_word(" !", 1.2, 1.3),
        ],
    )

    cues = build_subtitles([segment], STYLE)

    assert cues[0]["text"] == "Hello, world!"


def texts(cues):
    return [c["text"].replace("\n", " ") for c in cues]


def test_a_sentence_split_across_segments_stays_in_one_cue():
    # Real case (large-v3, sitcom): Whisper ended a segment at "for" and put
    # "you." in the next one. The times of "Musso's looking for" are from that run.
    first = words_segment(
        [("Musso's", 12.52, 12.92), ("looking", 12.92, 13.18), ("for", 13.18, 13.36)]
    )
    second = words_segment(evenly("you. Not a problem.", 13.36, 0.3))

    cues = build_subtitles([first, second], STYLE)

    assert texts(cues) == ["Musso's looking for you. Not a problem."]
    assert cues[0]["start"] == 12.52


def test_a_long_sentence_across_segments_breaks_at_the_sentence_end():
    first = words_segment(evenly("And we moved four sets of notes from Nick Bush", 0.0, 0.3))
    second = words_segment(
        evenly("class. Right. Then the bell rang and everyone went home", 3.0, 0.3)
    )

    cues = build_subtitles([first, second], STYLE)

    assert texts(cues)[0] == "And we moved four sets of notes from Nick Bush class. Right."


def test_a_pause_between_segments_still_splits():
    first = words_segment(evenly("hello there", 0.0))
    second = words_segment(evenly("anyone home", 5.0))

    assert texts(build_subtitles([first, second], STYLE)) == ["hello there", "anyone home"]


def test_words_of_two_segments_do_not_run_together():
    first = words_segment(evenly("looking for", 0.0))
    second = make_segment("you.", 0.8, 1.2, [make_word("you.", 0.8, 1.2)])  # no leading space

    assert texts(build_subtitles([first, second], STYLE)) == ["looking for you."]


def test_a_segment_without_word_timing_is_a_boundary_and_order_is_kept():
    before = words_segment(evenly("one two", 0.0))
    untimed = make_segment(" three four", 0.8, 1.6, None)
    after = words_segment(evenly("five six", 1.6))

    cues = build_subtitles([before, untimed, after], STYLE)

    assert texts(cues) == ["one two", "three four", "five six"]
    assert [c["start"] for c in cues] == sorted(c["start"] for c in cues)


def test_word_timestamps_are_on_by_default_in_the_model_config():
    assert ModelConfig().word_timestamps is True
