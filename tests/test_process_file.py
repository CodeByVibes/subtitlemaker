"""`process_file`, the library entry point shared by the CLI and the desktop app."""

import dataclasses
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


# --- keeping the transcript so the subtitles can be built again ---------------------------------


def test_recorded_segments_keep_what_the_segmenter_reads_and_nothing_else():
    from types import SimpleNamespace

    from subtitlemaker.pipeline import RecordedSegment, RecordedWord, record_segments

    original = SimpleNamespace(
        text=" Hello world.",
        start=1,
        end=2.5,
        words=[SimpleNamespace(word=" Hello", start=1.0, end=1.5, probability=0.9)],
        tokens=[1, 2, 3],  # heavy things that are not kept
        avg_logprob=-0.2,
    )
    untimed = SimpleNamespace(text=" ...", start=3.0, end=4.0, words=None)
    partly_timed = SimpleNamespace(
        text=" a",
        start=5.0,
        end=6.0,
        words=[SimpleNamespace(word=" a", start=None, end=None)],
    )

    first, second, third = record_segments([original, untimed, partly_timed])

    assert first == RecordedSegment(" Hello world.", 1.0, 2.5, (RecordedWord(" Hello", 1.0, 1.5),))
    assert isinstance(first.start, float)  # whole numbers become decimals
    assert second.words is None  # "no word timing" stays distinct from "no words"
    assert third.words == (RecordedWord(" a", None, None),)
    assert not hasattr(first, "tokens") and not hasattr(first, "avg_logprob")


def test_the_result_can_build_the_same_subtitles_again(fake_model, media, options, tmp_path):
    result = process_file(fake_model, media, {"srt": tmp_path / "a.srt"}, options)

    assert result.rebuild() == result.subtitles
    assert result.style == options.style


def test_the_result_can_build_other_subtitles_from_the_same_transcript(
    fake_model, media, options, tmp_path
):
    from subtitlemaker.segmenter import build_subtitles

    fake_model.segments = [
        make_segment(
            " one two three four five six seven eight nine ten eleven twelve.",
            0.0,
            12.0,
            [make_word(f" w{i}", i * 1.0, i * 1.0 + 0.9) for i in range(12)],
        )
    ]
    result = process_file(fake_model, media, {"srt": tmp_path / "a.srt"}, options)
    narrow = dataclasses.replace(options.style, max_line_length=12, max_lines=1)

    other = result.rebuild(narrow)

    assert other != result.subtitles  # a different style gives different subtitles
    assert len(other) > len(result.subtitles)
    assert other == build_subtitles(result.segments, narrow, result.text_language)
    assert result.rebuild() == result.subtitles  # and asking again for the original is unchanged


@pytest.mark.parametrize(
    ("changes", "language"),
    [
        ({}, "en"),  # the language Whisper detected
        ({"task": "translate"}, "en"),  # translated text is English whatever was spoken
        ({"multilingual": True}, None),  # it changes from segment to segment
    ],
)
def test_the_result_remembers_the_language_the_line_breaking_assumed(
    fake_model, media, options, tmp_path, changes, language
):
    fake_model.language = "sv" if changes.get("task") == "translate" else "en"

    result = process_file(
        fake_model, media, {"srt": tmp_path / "a.srt"}, dataclasses.replace(options, **changes)
    )

    assert result.text_language == language


def test_the_recorded_transcript_is_not_the_models_own_objects(
    fake_model, media, options, tmp_path
):
    result = process_file(fake_model, media, {"srt": tmp_path / "a.srt"}, options)

    assert all(type(segment).__name__ == "RecordedSegment" for segment in result.segments)


def test_the_recorded_snapshot_transcript_builds_the_stored_srt(tmp_path):
    # The real transcript fixture: record it, build it again, write it, compare with the
    # committed expected file. Nothing is lost by keeping only the recorded fields.
    from subtitlemaker.formats.srt import write_srt
    from subtitlemaker.pipeline import record_segments
    from tests.conftest import FIXTURES_DIR
    from tests.test_snapshot import STYLES, load_segments

    recorded = record_segments(load_segments())

    from subtitlemaker.segmenter import build_subtitles

    for name, style in STYLES.items():
        out = tmp_path / f"{name}.srt"
        write_srt(build_subtitles(recorded, style), out)

        assert out.read_text(encoding="utf-8") == (FIXTURES_DIR / f"expected-{name}.srt").read_text(
            encoding="utf-8"
        ), name


def _sentence_where_style_and_language_matter(fake_model):
    words = "She walked into the room and then the old man looked at the small dog on the floor"
    words = words.split()
    fake_model.segments = [
        make_segment(
            " " + " ".join(words) + ".",
            0.0,
            len(words) * 0.4,
            [make_word(f" {w}", i * 0.4, i * 0.4 + 0.3) for i, w in enumerate(words)],
        )
    ]


def test_the_result_rebuilds_with_the_style_the_run_used(fake_model, media, options, tmp_path):
    from subtitlemaker.config import SubtitleStyle

    _sentence_where_style_and_language_matter(fake_model)
    used = dataclasses.replace(options, style=SubtitleStyle(max_line_length=16, linger=0.2))

    result = process_file(fake_model, media, {"srt": tmp_path / "a.srt"}, used)

    assert result.style == used.style
    assert result.rebuild() == result.subtitles  # "the style used", not the defaults
    assert result.rebuild(SubtitleStyle()) != result.subtitles  # and it does make a difference


def test_the_result_rebuilds_with_the_language_the_run_assumed(
    fake_model, media, options, tmp_path
):
    from subtitlemaker.config import SubtitleStyle
    from subtitlemaker.segmenter import build_subtitles

    _sentence_where_style_and_language_matter(fake_model)
    narrow = dataclasses.replace(options, style=SubtitleStyle(max_line_length=16))
    mixed = dataclasses.replace(narrow, multilingual=True)

    english = process_file(fake_model, media, {"srt": tmp_path / "a.srt"}, narrow)
    unknown = process_file(fake_model, media, {"srt": tmp_path / "b.srt"}, mixed)

    # The language really changes where lines break in this sentence ...
    assert english.subtitles != unknown.subtitles
    # ... so each result has to rebuild with its own.
    assert (
        english.rebuild()
        == english.subtitles
        == build_subtitles(english.segments, narrow.style, "en")
    )
    assert (
        unknown.rebuild()
        == unknown.subtitles
        == build_subtitles(unknown.segments, narrow.style, None)
    )
