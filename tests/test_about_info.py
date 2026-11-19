"""What the About box says (no Qt needed)."""

import importlib.metadata
import sys
import types
from pathlib import Path

import pytest

import subtitlemaker
from subtitlemaker.gui.about_info import (
    CHANGELOG,
    CREDITS,
    HOMEPAGE,
    ISSUES,
    environment_report,
    package_version,
    shorten_home,
)

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
HOME = Path("/home/someone")


@pytest.fixture(autouse=True)
def no_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


# --- keeping the user name out of a pasted report ---------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/home/someone/.config/x.toml", "~/.config/x.toml"),
        ("/home/someone", "~"),
        ("a /home/someone/a and /home/someone/b", "a ~/a and ~/b"),
        ("(/home/someone/x)", "(~/x)"),
        ("'/home/someone/x'", "'~/x'"),
        ("path=/home/someone/x", "path=~/x"),  # after a sign, still the start of a path
        ("/home/someone2/x", "/home/someone2/x"),  # another folder with the same start
        ("/home/someonelse", "/home/someonelse"),
        ("/srv/home/someone/x", "/srv/home/someone/x"),  # inside another path: not the home
        ("nothing to hide", "nothing to hide"),
    ],
)
def test_the_home_folder_is_written_as_a_tilde(text, expected):
    assert shorten_home(text, HOME) == expected


def test_a_root_home_folder_is_left_alone():
    assert shorten_home("/etc/x and /root/y", Path("/")) == "/etc/x and /root/y"


def test_the_real_home_folder_is_used_by_default():
    text = f"{Path.home()}/.config/subtitlemaker"

    assert shorten_home(text) == "~/.config/subtitlemaker"


# --- the report -------------------------------------------------------------------------------


def report(**kwargs):
    return environment_report(
        qt="6.11.3 (PySide6 6.11.3), platform wayland",
        device="NVIDIA GPU found and ready (CUDA libraries installed).",
        settings_file=None,
        home=HOME,
        **kwargs,
    )


def test_the_report_has_what_a_bug_report_needs():
    lines = report().splitlines()

    assert lines[0] == f"SubtitleMaker {subtitlemaker.__version__}"
    assert lines[1].startswith(f"Python {sys.version.split()[0]} (")
    assert lines[2].startswith("OS: ")
    assert lines[3] == "Qt: 6.11.3 (PySide6 6.11.3), platform wayland"
    assert lines[4].startswith("faster-whisper ") and "CTranslate2 " in lines[4]
    assert lines[5] == "Device: NVIDIA GPU found and ready (CUDA libraries installed)."
    assert lines[6].startswith("Config file: ")


def test_the_report_says_whether_the_config_file_exists(tmp_path):
    assert report().splitlines()[6].endswith("(not found)")

    folder = tmp_path / "xdg" / "subtitlemaker"
    folder.mkdir(parents=True)
    (folder / "config.toml").write_text("[style]\nmax_lines = 1\n")

    assert not report().splitlines()[6].endswith("(not found)")


def test_the_settings_file_is_listed_when_there_is_one():
    assert "Settings file" not in report()

    with_file = environment_report(
        qt="6",
        device="d",
        settings_file=HOME / ".config" / "subtitlemaker" / "SubtitleMaker.conf",
        home=HOME,
    )

    assert "Settings file: ~/.config/subtitlemaker/SubtitleMaker.conf" in with_file


def test_the_report_never_contains_the_home_folder(tmp_path, monkeypatch):
    home = tmp_path / "people" / "alice"
    (home / ".config").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

    text = environment_report(
        qt="6",
        device="d",
        settings_file=home / ".config" / "subtitlemaker" / "SubtitleMaker.conf",
        home=home,
    )

    assert str(home) not in text and "alice" not in text
    assert "Config file: ~/.config/subtitlemaker/config.toml" in text


def _no_metadata(monkeypatch):
    """What a packaged app looks like: no package metadata at all."""

    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr("importlib.metadata.version", missing)


def test_without_package_metadata_the_module_is_asked(monkeypatch):
    _no_metadata(monkeypatch)
    module = types.ModuleType("fake_whisper_pkg")
    module.__version__ = "9.8.7"
    monkeypatch.setitem(sys.modules, "fake_whisper_pkg", module)

    assert package_version("fake-whisper-pkg") == "9.8.7"  # dashes become underscores
    assert package_version("some-distribution", "fake_whisper_pkg") == "9.8.7"  # or name it


def test_a_package_with_neither_metadata_nor_a_version_is_unknown(monkeypatch):
    _no_metadata(monkeypatch)
    versionless = types.ModuleType("versionless_pkg")
    wrong_kind = types.ModuleType("wrong_kind_pkg")
    wrong_kind.__version__ = (1, 2)  # not text
    monkeypatch.setitem(sys.modules, "versionless_pkg", versionless)
    monkeypatch.setitem(sys.modules, "wrong_kind_pkg", wrong_kind)

    assert package_version("versionless-pkg") == "unknown"
    assert package_version("wrong-kind-pkg") == "unknown"
    assert package_version("not-a-module-at-all") == "unknown"


def test_a_module_that_breaks_when_imported_is_unknown_not_a_crash(monkeypatch, tmp_path):
    _no_metadata(monkeypatch)
    (tmp_path / "exploding_pkg.py").write_text("raise RuntimeError('broken at import')\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    assert package_version("exploding-pkg") == "unknown"  # whatever it raises


def test_the_report_names_the_versions_even_in_a_packaged_app(monkeypatch):
    _no_metadata(monkeypatch)

    line = report().splitlines()[4]

    assert "unknown" not in line  # read from the modules instead
    assert line.startswith("faster-whisper 1.") and "CTranslate2 4." in line


def test_a_package_that_is_not_installed_is_reported_as_unknown():
    assert package_version("no-such-package-anywhere") == "unknown"
    assert package_version("pytest")[0].isdigit()


# --- the links and credits --------------------------------------------------------------------


def test_the_links_are_the_projects_urls():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    urls = pyproject["project"]["urls"]

    assert HOMEPAGE == urls["Homepage"]
    assert ISSUES == urls["Issues"]
    assert CHANGELOG == urls["Changelog"]


def test_the_credits_name_what_the_app_is_built_on():
    names = [name for name, address, licence in CREDITS]

    assert names == [
        "faster-whisper",
        "CTranslate2",
        "OpenAI Whisper models",
        "Qt for Python (PySide6)",
    ]
    assert all(address.startswith("https://") for name, address, licence in CREDITS)
    assert dict((n, lic) for n, a, lic in CREDITS)["Qt for Python (PySide6)"] == "LGPL-3.0"
