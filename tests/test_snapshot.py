"""Full output for a set of canned segments, compared with a stored SRT.

The scenarios in tests/fixtures/segments.json cover padded segments, close
speech, long sentences, pauses, empty segments, missing word timing,
overlapping segments and non-ASCII text.

When behaviour changes on purpose, regenerate and review the diff:

    UPDATE_SNAPSHOTS=1 uv run pytest tests/test_snapshot.py
"""

import json
import os

import pytest

from subtitlemaker.config import SubtitleStyle
from subtitlemaker.formats.srt import write_srt
from subtitlemaker.segmenter import build_subtitles
from tests.conftest import FIXTURES_DIR as FIXTURES
from tests.conftest import make_segment, make_word

STYLES = {
    "default": SubtitleStyle(),
    "one-line": SubtitleStyle(max_line_length=32, max_lines=1, min_duration=1.5, max_cps=15),
}


def load_segments():
    data = json.loads((FIXTURES / "segments.json").read_text(encoding="utf-8"))

    return [
        make_segment(
            item["text"],
            item["start"],
            item["end"],
            None if item["words"] is None else [make_word(*w) for w in item["words"]],
        )
        for item in data["segments"]
    ]


@pytest.mark.parametrize("name", STYLES)
def test_output_matches_snapshot(name, tmp_path):
    out = tmp_path / "out.srt"
    write_srt(build_subtitles(load_segments(), STYLES[name]), out)
    actual = out.read_text(encoding="utf-8")

    expected_path = FIXTURES / f"expected-{name}.srt"

    if os.environ.get("UPDATE_SNAPSHOTS"):
        expected_path.write_text(actual, encoding="utf-8")
        pytest.skip(f"snapshot {expected_path.name} updated")

    assert actual == expected_path.read_text(encoding="utf-8")
