"""Drawing the app icon for the Windows and macOS builds (needs PySide6)."""

import importlib.util
import struct
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QImage  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "packaging" / "build.py"
SVG = ROOT / "src" / "subtitlemaker" / "gui" / "resources" / "icon.svg"

pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="not running from a source checkout")


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location("subtitlemaker_build_icons", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["subtitlemaker_build_icons"] = module
    spec.loader.exec_module(module)

    return module


def test_the_svg_is_drawn_as_a_png_of_the_size_asked(build):
    data = build.render_png(SVG, 64)

    assert data.startswith(build.PNG_SIGNATURE)
    width, height = struct.unpack(">II", data[16:24])  # the PNG header
    assert (width, height) == (64, 64)


def test_the_picture_is_the_icon_with_a_see_through_background(build):
    image = QImage.fromData(build.render_png(SVG, 128), "PNG")

    assert image.hasAlphaChannel()
    assert image.pixelColor(0, 0).alpha() == 0  # the rounded corner is transparent
    assert image.pixelColor(64, 64).alpha() > 0  # the middle is drawn


def test_larger_sizes_are_drawn_larger_not_stretched(build):
    small = QImage.fromData(build.render_png(SVG, 32), "PNG")
    large = QImage.fromData(build.render_png(SVG, 512), "PNG")

    assert (small.width(), large.width()) == (32, 512)
    assert large.pixelColor(256, 256).alpha() > 0


def test_something_that_is_not_an_svg_is_an_error(build, tmp_path):
    bad = tmp_path / "bad.svg"
    bad.write_text("this is not an svg")

    with pytest.raises(RuntimeError, match="not a valid SVG"):
        build.render_png(bad, 16)


def test_windows_gets_an_ico_with_every_size(build, tmp_path):
    path = build.make_icons(SVG, tmp_path, "Windows")

    data = path.read_bytes()

    assert path.name == "SubtitleMaker.ico"
    assert struct.unpack("<HHH", data[:6]) == (0, 1, len(build.ICO_SIZES))


def test_macos_gets_an_icns_with_every_size(build, tmp_path):
    path = build.make_icons(SVG, tmp_path, "Darwin")

    data = path.read_bytes()

    assert path.name == "SubtitleMaker.icns"
    assert data[:4] == b"icns" and struct.unpack(">I", data[4:8])[0] == len(data)


def test_linux_needs_no_icon_file(build, tmp_path):
    assert build.make_icons(SVG, tmp_path, "Linux") is None
