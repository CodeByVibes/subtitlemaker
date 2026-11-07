import pytest

from subtitlemaker.config import SubtitleStyle
from subtitlemaker.segmenter import clean_text, split_into_lines

STYLE = SubtitleStyle()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  hello   world  ", "hello world"),
        ("hello , world !", "hello, world!"),
        ("so ; yes : no ?", "so; yes: no?"),
        ("( hello ) [ world ]", "(hello) [world]"),
        ("line\none\t two", "line one two"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_clean_text(raw, expected):
    assert clean_text(raw) == expected


def test_short_text_stays_on_one_line():
    assert split_into_lines("Hello there.", STYLE) == ["Hello there."]


def test_empty_text_gives_no_lines():
    assert split_into_lines("", STYLE) == []
    assert split_into_lines("   ", STYLE) == []


def test_long_text_is_balanced_over_two_lines():
    text = "the quick brown fox jumps over the lazy dog and keeps going"  # 59 chars

    lines = split_into_lines(text, STYLE)

    assert len(lines) == 2
    assert " ".join(lines) == text
    assert all(len(line) <= STYLE.max_line_length for line in lines)
    assert abs(len(lines[0]) - len(lines[1])) <= 8


def test_prefers_breaking_after_punctuation():
    # The balanced split would be "...the station, everybody" / "was already ...".
    # Breaking after the comma is less balanced but reads better.
    text = "When we arrived at the station, everybody was already waiting for us there"

    lines = split_into_lines(text, STYLE)

    assert lines == [
        "When we arrived at the station,",
        "everybody was already waiting for us there",
    ]


def test_respects_max_line_length_setting():
    text = "one two three four five six seven eight nine ten"
    style = SubtitleStyle(max_line_length=30)

    lines = split_into_lines(text, style)

    assert len(lines) == 2
    assert all(len(line) <= 30 for line in lines)


def test_unsplittable_text_falls_back_to_halving():
    # No two-line split fits within the limit, so it still returns two lines
    # rather than failing; the words are never lost.
    text = " ".join(["supercalifragilistic"] * 5)

    lines = split_into_lines(text, STYLE)

    assert len(lines) == 2
    assert " ".join(lines) == text


@pytest.mark.parametrize("max_lines", [1, 2])
def test_one_overlong_word_never_gives_an_empty_line(max_lines):
    word = "x" * 100
    style = SubtitleStyle(max_lines=max_lines)

    lines = split_into_lines(word, style)

    assert lines
    assert all(lines)
    assert len(lines) <= max_lines
    assert "".join(lines) == word
