import pytest

from subtitlemaker.formats.srt import format_srt_time, write_srt
from subtitlemaker.progress import TranscriptionProgress, format_time


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00,000"),
        (0.0004, "00:00:00,000"),
        (0.0006, "00:00:00,001"),
        (1.5, "00:00:01,500"),
        (61.25, "00:01:01,250"),
        (3599.9996, "01:00:00,000"),  # rounding carries into the hour
        (86400.123, "24:00:00,123"),
    ],
)
def test_format_srt_time(seconds, expected):
    assert format_srt_time(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00:00"), (59.9, "00:00:59"), (3661, "01:01:01"), (-5, "00:00:00")],
)
def test_format_time(seconds, expected):
    assert format_time(seconds) == expected


def test_write_srt(tmp_path):
    cues = [
        {"start": 0.5, "end": 2.0, "text": "Hello there."},
        {"start": 2.5, "end": 4.25, "text": "Two lines\nof text."},
    ]
    path = tmp_path / "out.srt"

    write_srt(cues, path)

    assert path.read_text(encoding="utf-8") == (
        "1\n00:00:00,500 --> 00:00:02,000\nHello there.\n\n"
        "2\n00:00:02,500 --> 00:00:04,250\nTwo lines\nof text.\n\n"
    )


def test_write_srt_is_utf8(tmp_path):
    path = tmp_path / "out.srt"

    write_srt([{"start": 0, "end": 1, "text": "שלום – åäö 🎬"}], path)

    assert "שלום – åäö 🎬" in path.read_text(encoding="utf-8")


def test_write_srt_empty(tmp_path):
    path = tmp_path / "out.srt"

    write_srt([], path)

    assert path.read_text() == ""


def test_write_srt_reports_unwritable_path(tmp_path):
    with pytest.raises(OSError):
        write_srt([], tmp_path / "missing-dir" / "out.srt")


def test_progress_disabled_is_a_noop():
    # Unknown duration (0) and enabled=False must not raise or draw anything.
    with TranscriptionProgress(0, console=None, enabled=True) as progress:
        progress.update(12.0)

    with TranscriptionProgress(60, console=None, enabled=False) as progress:
        progress.update(12.0)
