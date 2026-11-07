"""Output files are written atomically."""

import os
import stat

import pytest

from subtitlemaker.formats import FORMATS
from subtitlemaker.formats._atomic import atomic_open

CUES = [{"start": 0.0, "end": 1.0, "text": "Hello"}]


def leftovers(folder):
    return sorted(p.name for p in folder.iterdir())


def test_the_file_appears_complete_and_no_temp_file_stays(tmp_path):
    target = tmp_path / "a.srt"

    with atomic_open(target) as f:
        f.write("hello")

    assert target.read_text() == "hello"
    assert leftovers(tmp_path) == ["a.srt"]


def test_a_failure_mid_write_leaves_an_existing_file_untouched(tmp_path):
    target = tmp_path / "a.srt"
    target.write_text("old")

    with pytest.raises(RuntimeError), atomic_open(target) as f:
        f.write("half of the ne")
        raise RuntimeError("disk full")

    assert target.read_text() == "old"
    assert leftovers(tmp_path) == ["a.srt"]


def test_a_failure_mid_write_creates_no_file(tmp_path):
    target = tmp_path / "a.srt"

    with pytest.raises(RuntimeError), atomic_open(target) as f:
        f.write("half")
        raise RuntimeError("disk full")

    assert leftovers(tmp_path) == []


def test_a_new_file_gets_the_normal_umask_permissions(tmp_path):
    old = os.umask(0o022)

    try:
        with atomic_open(tmp_path / "a.srt") as f:
            f.write("x")

    finally:
        os.umask(old)

    assert stat.S_IMODE((tmp_path / "a.srt").stat().st_mode) == 0o644


def test_a_replaced_file_keeps_its_permissions(tmp_path):
    target = tmp_path / "a.srt"
    target.write_text("old")
    target.chmod(0o600)

    with atomic_open(target) as f:
        f.write("new")

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("name", list(FORMATS))
def test_every_format_writes_through_it(tmp_path, monkeypatch, name):
    target = tmp_path / f"a.{name}"
    target.write_text("old")

    original = FORMATS[name].write

    class Boom(RuntimeError):
        pass

    def broken_cues():
        yield CUES[0]
        raise Boom()

    with pytest.raises(Boom):
        original(broken_cues(), target)

    assert target.read_text() == "old"
    assert leftovers(tmp_path) == [target.name]
