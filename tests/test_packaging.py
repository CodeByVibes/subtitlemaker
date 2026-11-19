"""The desktop entry and icon in `packaging/` must match the app they launch."""

import configparser
import re
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    not (ROOT / "packaging").is_dir(), reason="not running from a source checkout"
)


@pytest.fixture(scope="module")
def entry():
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # keys are case sensitive in desktop files
    parser.read(ROOT / "packaging" / "subtitlemaker.desktop", encoding="utf-8")

    return parser["Desktop Entry"]


def test_the_entry_launches_the_command_the_package_installs(entry):
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert entry["Exec"] in pyproject["project"]["gui-scripts"]


def test_the_entry_matches_the_window_the_app_opens(entry):
    # On Wayland the app id is what ties a window to its launcher entry and icon.
    source = (ROOT / "src" / "subtitlemaker" / "gui" / "app.py").read_text(encoding="utf-8")
    app_id = re.search(r'setDesktopFileName\("([^"]+)"\)', source).group(1)

    assert entry["StartupWMClass"] == app_id
    assert (ROOT / "packaging" / f"{app_id}.desktop").is_file()  # the file name is the app id too


def test_the_entry_names_an_icon_that_is_shipped_alongside(entry):
    assert (ROOT / "packaging" / f"{entry['Icon']}.svg").is_file()


def test_the_icon_is_the_one_in_the_app():
    shipped = (ROOT / "packaging" / "subtitlemaker.svg").read_bytes()
    in_app = (ROOT / "src" / "subtitlemaker" / "gui" / "resources" / "icon.svg").read_bytes()

    assert shipped == in_app


def test_the_entry_has_what_a_launcher_needs(entry):
    assert entry["Type"] == "Application"
    assert entry["Name"] == "SubtitleMaker"
    assert entry["Terminal"] == "false"  # it is a window, not a terminal program
    assert entry["Categories"].endswith(";")  # lists end with a semicolon
