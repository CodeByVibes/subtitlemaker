import pytest

from subtitlemaker.config import SubtitleStyle
from subtitlemaker.segmenter import clean_text, lacks_punctuation, split_into_lines

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


def test_a_sentence_end_beats_a_more_balanced_break():
    # Real case (sitcom, large-v3). The old scoring gave
    # "I could look it up. I got a" / "friend of mine's brother who...".
    text = "I could look it up. I got a friend of mine's brother who..."

    assert split_into_lines(text, STYLE) == [
        "I could look it up.",
        "I got a friend of mine's brother who...",
    ]


def test_a_sentence_end_beats_a_comma():
    # Real case (Swedish drama, large-v3); the old scoring broke at "på / gubbar."
    text = "Stolpskott. Jag är så trött på gubbar. Min röv står på menyn."

    assert split_into_lines(text, STYLE) == [
        "Stolpskott. Jag är så trött på gubbar.",
        "Min röv står på menyn.",
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Real cases (Swedish drama, large-v3): short enough for one line.
        ("–Ja? –Vill du veta vad jag heter?", ["–Ja?", "–Vill du veta vad jag heter?"]),
        ("–Var har vi räker? –Jag vet inte.", ["–Var har vi räker?", "–Jag vet inte."]),
        (
            "–Gör vad du vill. Slå igen dörren. –Yes.",
            ["–Gör vad du vill. Slå igen dörren.", "–Yes."],
        ),
        # Hyphen and em dash work too.
        ("-Hi. -Hello there.", ["-Hi.", "-Hello there."]),
        ("—Hi. —Hello there.", ["—Hi.", "—Hello there."]),
    ],
)
def test_each_speaker_gets_their_own_line(text, expected):
    assert split_into_lines(text, STYLE) == expected


def test_a_minus_sign_is_not_a_new_speaker():
    assert split_into_lines("It was -20 degrees, so we stayed.", STYLE) == [
        "It was -20 degrees, so we stayed."
    ]


def test_a_dash_without_a_word_is_not_a_new_speaker():
    assert split_into_lines("Wait. - and then?", STYLE) == ["Wait. - and then?"]


def test_one_line_style_keeps_two_speakers_on_one_line():
    style = SubtitleStyle(max_lines=1)

    assert split_into_lines("–Ja? –Nej.", style) == ["–Ja? –Nej."]


def test_a_speaker_too_long_for_one_line_still_gives_valid_lines():
    # The second speaker's line (62 characters) can't go on a line of its own.
    text = "–Short. –And this second speaker goes on for far longer than a line."

    lines = split_into_lines(text, STYLE)

    assert len(lines) == 2
    assert all(0 < len(line) <= STYLE.max_line_length for line in lines)
    assert " ".join(lines) == text


@pytest.mark.parametrize(
    ("text", "language", "expected"),
    [
        # Real cases (large-v3): line 1 used to end on "or", "of" and "att".
        (
            "Either you work for the system or you make the system work for you.",
            "en",
            ["Either you work for the system", "or you make the system work for you."],
        ),
        (
            "I've confiscated this tape of your little cheating escapade.",
            "en",
            ["I've confiscated this tape", "of your little cheating escapade."],
        ),
        (
            "–Det är tuffare än att leva på pappas pengar.",
            "sv",
            ["–Det är tuffare än att leva", "på pappas pengar."],
        ),
    ],
)
def test_line_one_does_not_end_on_a_binding_word(text, language, expected):
    assert split_into_lines(text, STYLE, language) == expected


@pytest.mark.parametrize("language", [None, "de"])
def test_no_word_list_for_an_unknown_or_mixed_language(language):
    text = "Either you work for the system or you make the system work for you."

    assert split_into_lines(text, STYLE, language)[0] == "Either you work for the system or"


def test_pronouns_are_not_binding_words():
    # "he" ends a clause here; the old prototype list pushed the break elsewhere.
    text = "I've told him a thousand times he doesn't have to carry my books."

    assert split_into_lines(text, STYLE, "en")[0].endswith("he")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Real cases (sitcom, large-v3): the old scoring split both names.
        (
            "She was a Mona Lisa, a Sistine Chapel, a dog's playing poker,",
            ["She was a Mona Lisa, a Sistine Chapel,", "a dog's playing poker,"],
        ),
        (
            "We all went down to see Andrea Russell standing by the door.",
            ["We all went down to see", "Andrea Russell standing by the door."],
        ),
    ],
)
def test_a_name_is_not_split_over_two_lines(text, expected):
    assert split_into_lines(text, STYLE) == expected


def _segments(text, copies=1):
    from tests.conftest import make_segment

    return [make_segment(" " + text, 0.0, 1.0) for _ in range(copies)]


def test_a_transcript_without_punctuation_is_noticed():
    # Real style (large-v3, sitcom clip starting mid-sentence).
    text = "mikey what's going on what's going on in there are you okay now i get it okay robin"

    assert lacks_punctuation(_segments(text, 10), "en")


def test_a_normal_transcript_is_not():
    text = "Mikey, what's going on? What's going on in there? Are you okay? Now I get it."

    assert not lacks_punctuation(_segments(text, 10), "en")


def test_a_short_transcript_is_not_judged():
    assert not lacks_punctuation(_segments("one two three four five", 20), "en")  # 100 words


def test_languages_written_without_punctuation_are_not_judged():
    text = " ".join(["คำ"] * 200)

    assert not lacks_punctuation(_segments(text), "th")


def test_full_width_punctuation_counts():
    text = " ".join(["你好，我们走吧。"] * 200)

    assert not lacks_punctuation(_segments(text), "zh")
