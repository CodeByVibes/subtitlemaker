"""A sentence Whisper repeats with squeezed word timing is dropped (SUBMAKER-70).

Real case: Letterkenny S01E01 at 5:40. A 25 word sentence said once at 5:33 came
back, word for word, with all its words inside 0.08 s, and flashed up as a 0.1 s cue.
The rule is deliberately narrow: only a repeat, only impossible speed, only 6+ words.
"""

import pytest

from subtitlemaker.config import SubtitleStyle
from subtitlemaker.segmenter import build_subtitles
from tests.conftest import make_segment, make_word

STYLE = SubtitleStyle(start_offset=0.0)

SENTENCE = "And if that thing doesn't latch onto my nipple ring, which I'm pretty sure"


def timed(text, start, span):
    """A segment whose words are spread evenly over `span` seconds from `start`."""

    words = text.split()
    step = span / len(words)

    made = [
        make_word(" " + w, round(start + i * step, 4), round(start + (i + 1) * step, 4))
        for i, w in enumerate(words)
    ]

    return make_segment(" " + text, start, start + span, made)


def texts(cues):
    return [c["text"].replace("\n", " ") for c in cues]


def test_a_repeat_with_squeezed_timing_is_dropped():
    spoken = timed(SENTENCE, 333.0, 6.0)
    squeezed = timed(SENTENCE, 340.5, 0.08)  # the same words, all inside 0.08 s
    after = timed("Then they walked over and yanked it out.", 342.0, 3.0)

    with_repeat = build_subtitles([spoken, squeezed, after], STYLE)
    without = build_subtitles([spoken, after], STYLE)

    assert texts(with_repeat) == texts(without)
    assert [c["start"] for c in with_repeat] == [c["start"] for c in without]
    assert min(c["end"] - c["start"] for c in with_repeat) > 0.5  # no 0.1 s flash left


def test_case_and_punctuation_do_not_hide_a_repeat():
    spoken = timed("Where is my beautiful girlfriend, Virginia?", 696.0, 3.0)
    squeezed = timed("where is my beautiful girlfriend Virginia", 697.9, 0.26)

    assert len(build_subtitles([spoken, squeezed], STYLE)) == len(build_subtitles([spoken], STYLE))


def test_a_repeat_of_only_the_end_of_a_sentence_is_dropped_too():
    spoken = timed("I think you should go home and rest, Daryl.", 10.0, 4.0)
    squeezed = timed("you should go home and rest, Daryl.", 14.5, 0.1)

    assert texts(build_subtitles([spoken, squeezed], STYLE)) == texts(
        build_subtitles([spoken], STYLE)
    )


def test_squeezed_words_that_are_not_a_repeat_are_kept():
    # Fast or badly timed speech that says something new must never be lost.
    spoken = timed(SENTENCE, 333.0, 6.0)
    new = timed("We need to talk to her about this today.", 340.5, 0.1)

    cues = build_subtitles([spoken, new], STYLE)

    assert any("talk to her" in t for t in texts(cues))


def test_a_real_repetition_with_normal_timing_is_kept():
    # Someone really says it twice: the second has a human speaking rate.
    first = timed(SENTENCE, 333.0, 6.0)
    second = timed(SENTENCE, 340.5, 6.0)

    cues = build_subtitles([first, second], STYLE)

    assert " ".join(texts(cues)).count("nipple ring") == 2


def test_a_short_squeezed_repeat_is_kept():
    # Four words can honestly be said that fast, and "och så får du" is a common phrase.
    spoken = timed("Och så får du ett glas vatten.", 10.0, 3.0)
    short = timed("Och så får du", 14.0, 0.2)

    assert len(build_subtitles([spoken, short], STYLE)) == 2


def test_a_repeat_from_long_ago_is_kept():
    # More than 80 words in between: this is the same line used again, not a stutter.
    spoken = timed(SENTENCE, 10.0, 6.0)
    filler = [
        timed("one two three four five six seven eight nine ten", 20.0 + i * 3, 2.5)
        for i in range(9)
    ]
    squeezed = timed(SENTENCE, 60.0, 0.08)

    cues = build_subtitles([spoken, *filler, squeezed], STYLE)

    assert " ".join(texts(cues)).count("nipple ring") == 2


def test_a_dropped_repeat_does_not_make_the_next_repeat_look_new():
    spoken = timed(SENTENCE, 333.0, 6.0)
    first = timed(SENTENCE, 340.5, 0.08)
    second = timed(SENTENCE, 340.9, 0.08)

    assert texts(build_subtitles([spoken, first, second], STYLE)) == texts(
        build_subtitles([spoken], STYLE)
    )


@pytest.mark.parametrize("span", [0.0, 0.05, 0.29])
def test_the_speed_limit_is_twenty_words_per_second(span):
    spoken = timed("One two three four five six.", 1.0, 3.0)  # 6 words
    repeat = timed("One two three four five six.", 5.0, span)  # 6 words in under 0.3 s

    assert len(build_subtitles([spoken, repeat], STYLE)) == 1


def test_six_words_in_just_over_the_limit_is_kept():
    spoken = timed("One two three four five six.", 1.0, 3.0)
    repeat = timed("One two three four five six.", 5.0, 0.31)  # about 19 words per second

    assert len(build_subtitles([spoken, repeat], STYLE)) == 2


def test_a_repeat_of_text_without_word_timing_is_found_too():
    # The earlier segment had no word timing (so it was spread over its duration).
    spoken = make_segment(" " + SENTENCE, 333.0, 339.0, None)
    squeezed = timed(SENTENCE, 340.5, 0.08)

    assert len(build_subtitles([spoken, squeezed], STYLE)) == len(build_subtitles([spoken], STYLE))


def test_a_repeat_with_one_changed_word_is_still_dropped():
    spoken = timed(SENTENCE, 333.0, 6.0)
    changed = timed(SENTENCE.replace("sure", "certain"), 340.5, 0.08)

    cues = build_subtitles([spoken, changed], STYLE)

    assert len(cues) == 1


def test_the_text_of_a_dropped_repeat_is_reported():
    spoken = timed(SENTENCE, 333.0, 6.0)
    squeezed = timed(SENTENCE, 340.5, 0.08)
    dropped = []

    build_subtitles([spoken, squeezed], STYLE, dropped=dropped)

    assert dropped == [SENTENCE]
