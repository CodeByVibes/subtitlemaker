"""`process_file`, the library entry point shared by the CLI and the desktop app."""

import threading

import pytest

from subtitlemaker.config import ModelConfig, SubtitleStyle
from subtitlemaker.pipeline import Cancelled, FileResult, Options, OutputError, process_file
from tests.conftest import make_segment, make_word


@pytest.fixture(autouse=True)
def known_duration(monkeypatch):
    """The media file is empty, so the real duration lookup would fail (and warn)."""

    monkeypatch.setattr("subtitlemaker.pipeline.get_duration", lambda path: 10.0)


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "talk.mp3"
    path.write_bytes(b"")  # never decoded: the model is fake
    return path


@pytest.fixture
def options():
    return Options(
        style=SubtitleStyle(),
        model_config=ModelConfig(),
        task="transcribe",
        languages=[],
        language_hint=None,
        multilingual=False,
        condition_on_previous_text=True,
        detect_segments=1,
        detect_threshold=0.5,
    )


@pytest.fixture
def two_segments(fake_model):
    fake_model.segments = [
        make_segment(" One.", 0.0, 4.0, [make_word(" One.", 1.0, 1.5)]),
        make_segment(" Two.", 5.0, 9.0, [make_word(" Two.", 6.0, 6.5)]),
    ]

    return fake_model


def test_returns_what_happened(fake_model, media, options, tmp_path):
    out = tmp_path / "talk.srt"

    result = process_file(fake_model, media, {"srt": out}, options)

    assert isinstance(result, FileResult)
    assert result.input_file == media
    assert result.outputs == {"srt": out}
    assert result.language == "en"
    assert result.language_probability == pytest.approx(0.99)
    assert len(result.subtitles) == 1
    assert len(result.segments) == 1  # the raw segments, kept for re-segmenting
    assert result.warnings == []
    assert out.exists()


def test_progress_starts_at_zero_and_ends_at_the_duration(
    two_segments, media, options, tmp_path, monkeypatch
):
    monkeypatch.setattr("subtitlemaker.pipeline.get_duration", lambda path: 10.0)
    reports = []

    process_file(
        two_segments,
        media,
        {"srt": tmp_path / "a.srt"},
        options,
        on_progress=lambda position, duration: reports.append((position, duration)),
    )

    assert reports == [(0.0, 10.0), (4.0, 10.0), (9.0, 10.0), (10.0, 10.0)]


def test_progress_is_optional(fake_model, media, options, tmp_path):
    process_file(fake_model, media, {"srt": tmp_path / "a.srt"}, options)


def test_cancelling_stops_after_the_current_segment_and_writes_nothing(
    two_segments, media, options, tmp_path
):
    out = tmp_path / "a.srt"
    cancel = threading.Event()
    seen = []

    def on_progress(position, duration):
        seen.append(position)

        if position == 4.0:  # the first segment is done
            cancel.set()

    with pytest.raises(Cancelled):
        process_file(
            two_segments, media, {"srt": out}, options, on_progress=on_progress, cancel=cancel
        )

    assert 9.0 not in seen  # the second segment was never taken
    assert not out.exists()


def test_cancelling_before_the_start_never_calls_the_model(fake_model, media, options, tmp_path):
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(Cancelled):
        process_file(fake_model, media, {"srt": tmp_path / "a.srt"}, options, cancel=cancel)

    assert fake_model.calls == []


def test_a_write_failure_is_an_output_error_with_a_ready_message(
    fake_model, media, options, tmp_path
):
    target = tmp_path / "missing-folder" / "a.srt"

    with pytest.raises(OutputError, match="couldn't write .*a.srt"):
        process_file(fake_model, media, {"srt": target}, options)


def test_unreadable_duration_becomes_a_warning_in_the_result(
    fake_model, media, options, tmp_path, monkeypatch
):
    def broken(path):
        raise OSError("no such stream")

    monkeypatch.setattr("subtitlemaker.pipeline.get_duration", broken)

    result = process_file(fake_model, media, {"srt": tmp_path / "a.srt"}, options)

    assert result.duration == 0.0
    assert result.warnings == ["couldn't determine duration: no such stream"]


def test_missing_punctuation_becomes_a_warning_in_the_result(fake_model, media, options, tmp_path):
    fake_model.segments = [
        make_segment(
            " mikey what's going on what's going on in there are you okay now i get it",
            i * 5.0,
            i * 5.0 + 4.0,
        )
        for i in range(12)
    ]

    result = process_file(fake_model, media, {"srt": tmp_path / "a.srt"}, options)

    assert len(result.warnings) == 1
    assert "almost no punctuation for talk.mp3" in result.warnings[0]
