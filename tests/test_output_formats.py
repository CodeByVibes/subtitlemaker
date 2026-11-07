from pathlib import Path

import pytest

from subtitlemaker.formats import FORMATS, output_path, parse_formats
from subtitlemaker.formats.txt import write_txt
from subtitlemaker.formats.vtt import format_vtt_time, write_vtt

CUES = [
    {"start": 0.5, "end": 2.0, "text": "Hello there."},
    {"start": 2.5, "end": 4.25, "text": "Two lines\nof text."},
]


# --- registry -------------------------------------------------------------


def test_registry_has_the_three_formats():
    assert {name: f.extension for name, f in FORMATS.items()} == {
        "srt": "srt",
        "vtt": "vtt",
        "txt": "txt",
    }


@pytest.mark.parametrize("name", ["srt", "vtt", "txt"])
def test_every_registered_format_writes_a_file(name, tmp_path):
    path = tmp_path / f"out.{name}"

    FORMATS[name].write(CUES, path)

    assert path.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("name", ["srt", "vtt", "txt"])
def test_every_format_accepts_no_cues_and_non_ascii(name, tmp_path):
    path = tmp_path / "x"

    FORMATS[name].write([], path)
    FORMATS[name].write([{"start": 0, "end": 1, "text": "שלום – åäö 🎬"}], path)

    assert "שלום – åäö 🎬" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ["srt"]),
        ("", ["srt"]),
        ("srt", ["srt"]),
        ("VTT", ["vtt"]),
        ("srt,vtt", ["srt", "vtt"]),
        ("srt vtt  txt", ["srt", "vtt", "txt"]),
        ("txt, srt, txt", ["txt", "srt"]),
    ],
)
def test_parse_formats(value, expected):
    assert parse_formats(value) == expected


def test_parse_formats_rejects_unknown_names():
    with pytest.raises(ValueError, match="ass"):
        parse_formats("srt,ass")


@pytest.mark.parametrize(
    ("base", "fmt", "expected"),
    [
        ("talk", "srt", "talk.srt"),
        ("talk.srt", "vtt", "talk.vtt"),  # a known extension is replaced
        ("TALK.VTT", "txt", "TALK.txt"),
        ("show.s01e01", "srt", "show.s01e01.srt"),  # other dots are part of the name
        ("dir/my.video", "vtt", "dir/my.video.vtt"),
    ],
)
def test_output_path(base, fmt, expected):
    assert output_path(Path(base), fmt) == Path(expected)


# --- WebVTT ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00.000"),
        (1.5, "00:00:01.500"),
        (3599.9996, "01:00:00.000"),
        (90061.5, "25:01:01.500"),
    ],
)
def test_format_vtt_time_uses_a_dot(seconds, expected):
    assert format_vtt_time(seconds) == expected


def test_write_vtt(tmp_path):
    path = tmp_path / "out.vtt"

    write_vtt(CUES, path)

    assert path.read_text(encoding="utf-8") == (
        "WEBVTT\n\n"
        "00:00:00.500 --> 00:00:02.000\nHello there.\n\n"
        "00:00:02.500 --> 00:00:04.250\nTwo lines\nof text.\n\n"
    )


def test_write_vtt_with_no_cues_is_still_a_valid_file(tmp_path):
    path = tmp_path / "out.vtt"

    write_vtt([], path)

    assert path.read_text(encoding="utf-8") == "WEBVTT\n\n"


def test_write_vtt_escapes_markup_characters(tmp_path):
    path = tmp_path / "out.vtt"
    cue = {"start": 0, "end": 1, "text": "Tom & Jerry <b> --> next"}

    write_vtt([cue], path)

    text = path.read_text(encoding="utf-8")
    assert "Tom &amp; Jerry &lt;b&gt; --&gt; next" in text
    assert text.count("-->") == 1  # only the timing line


# --- plain text -----------------------------------------------------------


def test_write_txt_is_one_cue_per_line(tmp_path):
    path = tmp_path / "out.txt"

    write_txt(CUES, path)

    assert path.read_text(encoding="utf-8") == "Hello there.\nTwo lines of text.\n"


def test_write_txt_with_no_cues_is_empty(tmp_path):
    path = tmp_path / "out.txt"

    write_txt([], path)

    assert path.read_text(encoding="utf-8") == ""
