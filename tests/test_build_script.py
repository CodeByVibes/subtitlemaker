"""packaging/build.py: the parts that run on every system (names, icons, archives, checksums)."""

import hashlib
import importlib.util
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

import subtitlemaker
from subtitlemaker import __version__

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "packaging" / "build.py"

pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="not running from a source checkout")


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location("subtitlemaker_build", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["subtitlemaker_build"] = module
    spec.loader.exec_module(module)

    return module


PNG = b"\x89PNG\r\n\x1a\n" + b"fake image data"


# --- names ------------------------------------------------------------------------------------


def test_the_version_comes_from_the_one_place_it_is_defined(build):
    assert build.app_version() == subtitlemaker.__version__


def test_a_missing_version_is_an_error(build, tmp_path):
    (tmp_path / "src" / "subtitlemaker").mkdir(parents=True)
    (tmp_path / "src" / "subtitlemaker" / "__init__.py").write_text("# no version here\n")

    with pytest.raises(RuntimeError, match="no __version__"):
        build.app_version(tmp_path)


@pytest.mark.parametrize(
    ("system", "machine", "tag"),
    [
        ("Linux", "x86_64", "linux-x86_64"),
        ("Linux", "aarch64", "linux-aarch64"),
        ("Windows", "AMD64", "windows-x64"),
        ("Windows", "x86_64", "windows-x64"),
        ("Darwin", "arm64", "macos-arm64"),
        ("Darwin", "x86_64", "macos-x86_64"),
    ],
)
def test_each_system_gets_its_download_tag(build, system, machine, tag):
    assert build.platform_tag(system, machine) == tag


def test_an_unsupported_system_is_an_error(build):
    with pytest.raises(RuntimeError, match="unsupported system"):
        build.platform_tag("FreeBSD", "amd64")


def test_the_download_names(build):
    assert (
        build.artifact_name("0.3.0", "linux-x86_64", ".tar.gz")
        == "SubtitleMaker-0.3.0-linux-x86_64.tar.gz"
    )
    assert (
        build.artifact_name("0.3.0", "macos-arm64", ".dmg") == "SubtitleMaker-0.3.0-macos-arm64.dmg"
    )


# --- the Windows icon -------------------------------------------------------------------------


def test_an_ico_holds_every_image_at_the_right_offset(build):
    images = {16: PNG + b"a", 32: PNG + b"bb", 256: PNG + b"ccc"}

    data = build.ico_bytes(images)

    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, 3)  # an icon file with three images

    sizes = []

    for index, size in enumerate(sorted(images)):
        width, height, colours, zero, planes, bits, length, offset = struct.unpack(
            "<BBBBHHII", data[6 + 16 * index : 6 + 16 * (index + 1)]
        )
        sizes.append(width)
        assert width == height and (colours, zero, planes, bits) == (0, 0, 1, 32)
        assert data[offset : offset + length] == images[size]  # the entry points at its image

    assert sizes == [16, 32, 0]  # 256 pixels is written as 0


@pytest.mark.parametrize("images", [{}, {512: PNG}])
def test_an_ico_refuses_what_it_cannot_hold(build, images):
    with pytest.raises(ValueError):
        build.ico_bytes(images)


# --- the macOS icon ---------------------------------------------------------------------------


def test_an_icns_is_a_list_of_typed_png_entries(build):
    images = {16: PNG + b"a", 128: PNG + b"bb", 1024: PNG + b"ccc"}

    data = build.icns_bytes(images)

    assert data[:4] == b"icns" and struct.unpack(">I", data[4:8])[0] == len(data)

    position, found = 8, []

    while position < len(data):
        kind = data[position : position + 4]
        length = struct.unpack(">I", data[position + 4 : position + 8])[0]
        found.append((kind, data[position + 8 : position + length]))
        position += length

    assert position == len(data)  # no stray bytes
    assert found == [(b"icp4", images[16]), (b"ic07", images[128]), (b"ic10", images[1024])]


@pytest.mark.parametrize("images", [{}, {17: PNG}])
def test_an_icns_refuses_what_it_cannot_hold(build, images):
    with pytest.raises(ValueError):
        build.icns_bytes(images)


# --- checksums --------------------------------------------------------------------------------


def test_a_checksum_is_the_sha256(build, tmp_path):
    path = tmp_path / "abc.bin"
    path.write_bytes(b"abc")

    assert build.sha256(path) == hashlib.sha256(b"abc").hexdigest()
    assert build.sha256(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_the_checksum_file_has_one_sorted_line_per_download(build, tmp_path):
    b, a = tmp_path / "b.zip", tmp_path / "a.zip"
    a.write_bytes(b"first")
    b.write_bytes(b"second")

    target = build.write_checksums([b, a], tmp_path / "SHA256SUMS")

    lines = target.read_text().splitlines()

    assert lines == [
        f"{hashlib.sha256(b'first').hexdigest()}  a.zip",
        f"{hashlib.sha256(b'second').hexdigest()}  b.zip",
    ]


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="no sha256sum")
def test_the_checksum_file_is_accepted_by_sha256sum(build, tmp_path):
    # An independent tool, as a user would check a download.
    (tmp_path / "x.bin").write_bytes(b"payload")
    build.write_checksums([tmp_path / "x.bin"], tmp_path / "SHA256SUMS")

    result = subprocess.run(
        ["sha256sum", "-c", "SHA256SUMS"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 0 and "x.bin: OK" in result.stdout


# --- archives ---------------------------------------------------------------------------------


@pytest.fixture
def app_folder(tmp_path):
    folder = tmp_path / "dist" / "SubtitleMaker"
    (folder / "_internal" / "lib").mkdir(parents=True)
    (folder / "SubtitleMaker").write_bytes(b"program")
    (folder / "_internal" / "lib" / "data.bin").write_bytes(b"data")

    return folder


def test_the_tar_holds_the_app_under_one_folder(build, app_folder, tmp_path):
    out = tmp_path / "out"
    out.mkdir()

    target = build.package_tar(app_folder, out, "0.3.0", "linux-x86_64")

    assert target.name == "SubtitleMaker-0.3.0-linux-x86_64.tar.gz"

    with tarfile.open(target) as archive:
        names = sorted(archive.getnames())
        assert archive.extractfile("SubtitleMaker/SubtitleMaker").read() == b"program"

    assert names == [
        "SubtitleMaker",
        "SubtitleMaker/SubtitleMaker",
        "SubtitleMaker/_internal",
        "SubtitleMaker/_internal/lib",
        "SubtitleMaker/_internal/lib/data.bin",
    ]


def test_the_zip_holds_the_app_under_one_folder(build, app_folder, tmp_path):
    out = tmp_path / "out"
    out.mkdir()

    target = build.package_zip(app_folder, out, "0.3.0", "windows-x64")

    assert target.name == "SubtitleMaker-0.3.0-windows-x64.zip"

    with zipfile.ZipFile(target) as archive:
        names = sorted(archive.namelist())
        assert archive.read("SubtitleMaker/SubtitleMaker") == b"program"
        assert archive.testzip() is None

    assert names == [
        "SubtitleMaker/SubtitleMaker",
        "SubtitleMaker/_internal/lib/data.bin",
    ]  # forward slashes, whatever system built it


def test_the_zip_is_compressed(build, tmp_path):
    folder = tmp_path / "dist" / "SubtitleMaker"
    folder.mkdir(parents=True)
    (folder / "big.bin").write_bytes(b"A" * 100_000)  # compresses to almost nothing
    out = tmp_path / "out"
    out.mkdir()

    target = build.package_zip(folder, out, "0.3.0", "windows-x64")

    with zipfile.ZipFile(target) as archive:
        info = archive.getinfo("SubtitleMaker/big.bin")

    assert info.compress_type == zipfile.ZIP_DEFLATED
    assert target.stat().st_size < 10_000  # not the 100 kB it holds


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        ("Linux", "SubtitleMaker"),
        ("Windows", "SubtitleMaker.exe"),
        ("Darwin", "Contents/MacOS/SubtitleMaker"),
    ],
)
def test_the_program_inside_what_pyinstaller_makes(build, monkeypatch, system, expected):
    monkeypatch.setattr(build.platform, "system", lambda: system)

    assert build.executable(Path("/x/SubtitleMaker")) == Path("/x/SubtitleMaker") / expected


# --- the spec and the driver agree ------------------------------------------------------------


def test_the_spec_reads_the_variables_the_driver_sets(build):
    spec = (ROOT / "packaging" / "subtitlemaker.spec").read_text(encoding="utf-8")
    driver = SCRIPT.read_text(encoding="utf-8")

    for variable in ("SUBTITLEMAKER_VERSION", "SUBTITLEMAKER_ICON"):
        assert variable in spec and variable in driver


def test_the_icon_path_given_to_pyinstaller_is_absolute(build, monkeypatch, tmp_path):
    # A relative path is read from the spec's folder by PyInstaller, not from where we run.
    import types

    fake = types.ModuleType("PyInstaller.__main__")
    fake.run = lambda args: None
    monkeypatch.setitem(sys.modules, "PyInstaller", types.ModuleType("PyInstaller"))
    monkeypatch.setitem(sys.modules, "PyInstaller.__main__", fake)
    monkeypatch.setattr(sys.modules["PyInstaller"], "__main__", fake, raising=False)
    monkeypatch.setenv("SUBTITLEMAKER_ICON", "")  # restored afterwards
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="did not make"):  # nothing was built: fine here
        build.run_pyinstaller("1.0", Path("icons/a.ico"), Path("dist"), Path("work"))

    assert Path(os.environ["SUBTITLEMAKER_ICON"]).is_absolute()


def test_the_spec_bundles_what_a_frozen_app_cannot_find_on_its_own():
    spec = (ROOT / "packaging" / "subtitlemaker.spec").read_text(encoding="utf-8")

    assert 'collect_data_files("faster_whisper")' in spec  # the voice activity model
    assert 'collect_data_files("subtitlemaker")' in spec  # the icon
    assert '"PySide6.QtSvg"' in spec  # the SVG plugin that draws the icon


def test_the_build_group_has_pyinstaller_and_is_not_part_of_dev():
    groups = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "dependency-groups"
    ]

    assert any(d.startswith("pyinstaller") for d in groups["build"])
    assert not any("pyinstaller" in d for d in groups["dev"])


# --- the AppImage -----------------------------------------------------------------------------

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="uses sh scripts")


def fake_app(folder: Path, body: str = 'echo "args: $@"') -> Path:
    """A stand-in for the PyInstaller output: a folder with a `SubtitleMaker` program in it."""

    (folder / "_internal").mkdir(parents=True)
    program = folder / "SubtitleMaker"
    program.write_text(f"#!/bin/sh\n{body}\n")
    program.chmod(0o755)
    (folder / "_internal" / "libreal.so.1").write_bytes(b"lib")
    (folder / "_internal" / "liblink.so").symlink_to("libreal.so.1")

    return folder


def test_the_appimage_entry_launches_the_app_by_the_name_apprun_finds(build):
    text = build.desktop_entry_for_appimage("0.3.0")

    assert "Exec=SubtitleMaker\n" in text and "Exec=subtitlemaker-gui" not in text
    assert text.endswith("X-AppImage-Version=0.3.0\n")
    assert "Name=SubtitleMaker" in text and "Icon=subtitlemaker" in text  # the rest is kept


def test_the_appimage_entry_notices_when_the_desktop_file_changed(build, monkeypatch, tmp_path):
    (tmp_path / "subtitlemaker.desktop").write_text("[Desktop Entry]\nExec=something-else\n")
    monkeypatch.setattr(build, "PACKAGING", tmp_path)

    with pytest.raises(RuntimeError, match="no longer runs subtitlemaker-gui"):
        build.desktop_entry_for_appimage("0.3.0")


def test_the_appdir_has_what_appimagetool_needs(build, tmp_path):
    app = fake_app(tmp_path / "dist" / "SubtitleMaker")

    appdir = build.make_appdir(app, tmp_path / "AppDir", "0.3.0", PNG)

    assert (appdir / "AppRun").stat().st_mode & 0o111  # executable
    assert (appdir / "subtitlemaker.desktop").read_text().count("Exec=SubtitleMaker") == 1
    assert (appdir / "subtitlemaker.png").read_bytes() == PNG
    assert (appdir / ".DirIcon").is_symlink()
    assert (appdir / ".DirIcon").resolve() == (appdir / "subtitlemaker.png").resolve()
    assert (appdir / "usr/bin/SubtitleMaker/SubtitleMaker").is_file()
    # symbolic links inside the app stay links (copying them as files would bloat the image)
    assert (appdir / "usr/bin/SubtitleMaker/_internal/liblink.so").is_symlink()


def test_the_appdir_starts_clean_each_time(build, tmp_path):
    app = fake_app(tmp_path / "dist" / "SubtitleMaker")
    appdir = tmp_path / "AppDir"
    appdir.mkdir()
    (appdir / "leftover.txt").write_text("from an earlier build")

    build.make_appdir(app, appdir, "0.3.0", PNG)

    assert not (appdir / "leftover.txt").exists()


@posix_only
def test_apprun_starts_the_app_and_hands_on_the_arguments(build, tmp_path):
    app = fake_app(tmp_path / "dist" / "SubtitleMaker")
    appdir = build.make_appdir(app, tmp_path / "AppDir", "0.3.0", PNG)

    result = subprocess.run(
        [str(appdir / "AppRun"), "--self-check", "a b"], capture_output=True, text=True
    )

    assert result.returncode == 0
    assert result.stdout == "args: --self-check a b\n"


@posix_only
def test_apprun_works_when_started_through_a_link_from_another_folder(build, tmp_path):
    # An AppImage is mounted somewhere else and often started through a symlink.
    app = fake_app(tmp_path / "dist" / "SubtitleMaker")
    appdir = build.make_appdir(app, tmp_path / "AppDir", "0.3.0", PNG)
    link = tmp_path / "elsewhere" / "run-it"
    link.parent.mkdir()
    link.symlink_to(appdir / "AppRun")

    result = subprocess.run([str(link)], capture_output=True, text=True, cwd=tmp_path / "elsewhere")

    assert result.returncode == 0 and result.stdout == "args: \n"


@posix_only
def test_the_appimage_tool_is_run_the_way_it_needs(build, tmp_path):
    app = fake_app(tmp_path / "dist" / "SubtitleMaker")
    out, work = tmp_path / "out", tmp_path / "work"
    out.mkdir()
    work.mkdir()
    record = tmp_path / "record.txt"
    tool = tmp_path / "appimagetool"
    tool.write_text(
        f'#!/bin/sh\necho "$1|$2|$ARCH|$APPIMAGE_EXTRACT_AND_RUN" > {record}\ntouch "$2"\n'
    )
    tool.chmod(0o755)

    target = build.package_appimage(app, out, "0.3.0", "linux-x86_64", tool, work, PNG)

    appdir, written, arch, extract = record.read_text().strip().split("|")

    assert target == out / "SubtitleMaker-0.3.0-linux-x86_64.AppImage" and target.exists()
    assert Path(appdir) == work / "SubtitleMaker.AppDir" and Path(written) == target
    assert arch  # the tool refuses to run without ARCH
    assert extract == "1"  # and a build machine often has no FUSE


@posix_only
def test_a_failing_tool_stops_the_build(build, tmp_path):
    app = fake_app(tmp_path / "dist" / "SubtitleMaker")
    tool = tmp_path / "appimagetool"
    tool.write_text("#!/bin/sh\nexit 1\n")
    tool.chmod(0o755)

    with pytest.raises(subprocess.CalledProcessError):
        build.package_appimage(app, tmp_path, "0.3.0", "linux-x86_64", tool, tmp_path, PNG)


# --- the macOS disk image ---------------------------------------------------------------------


def test_the_dmg_holds_the_app_and_a_link_to_applications(build, tmp_path, monkeypatch):
    app = tmp_path / "dist" / "SubtitleMaker.app"
    (app / "Contents" / "Frameworks").mkdir(parents=True)
    (app / "Contents" / "Frameworks" / "Qt.framework").mkdir()
    (app / "Contents" / "Frameworks" / "Current").symlink_to("Qt.framework")
    (app / "Contents" / "Info.plist").write_text("plist")
    out, work = tmp_path / "out", tmp_path / "work"
    out.mkdir()
    work.mkdir()
    calls = []
    monkeypatch.setattr(build.subprocess, "run", lambda command, **kw: calls.append((command, kw)))

    target = build.package_dmg(app, out, "0.3.0", "macos-arm64", work)

    staging = work / "dmg"
    command, kwargs = calls[0]

    assert target == out / "SubtitleMaker-0.3.0-macos-arm64.dmg"
    assert command[:2] == ["hdiutil", "create"] and kwargs["check"] is True
    assert command[command.index("-srcfolder") + 1] == str(staging)
    assert command[command.index("-volname") + 1] == "SubtitleMaker"
    assert command[command.index("-format") + 1] == "UDZO"  # compressed
    assert command[-1] == str(target)
    assert (staging / "SubtitleMaker.app" / "Contents" / "Info.plist").read_text() == "plist"
    assert (staging / "SubtitleMaker.app" / "Contents" / "Frameworks" / "Current").is_symlink()
    assert (staging / "Applications").is_symlink()
    assert (staging / "Applications").readlink() == Path("/Applications")  # drag to install


# --- checking the built app before packaging --------------------------------------------------


@posix_only
def test_the_built_app_is_asked_to_check_itself_and_its_report_is_shown(build, tmp_path, capsys):
    record = tmp_path / "args.txt"
    app = fake_app(
        tmp_path / "dist" / "SubtitleMaker",
        f'echo "$QT_QPA_PLATFORM $@" > {record}\n'
        'while [ $# -gt 0 ]; do [ "$1" = "--report" ] && echo "ok  fake: fine" > "$2"; shift; done',
    )

    code = build.self_check(app, tmp_path / "clip.flac", "tiny", tmp_path / "report.txt")

    assert code == 0
    assert "ok  fake: fine" in capsys.readouterr().out  # a windowed app prints nothing itself
    assert record.read_text().split() == [
        "offscreen",
        "--self-check",
        "--audio",
        str(tmp_path / "clip.flac"),
        "--model",
        "tiny",
        "--report",
        str(tmp_path / "report.txt"),
    ]


@posix_only
def test_a_failing_self_check_is_returned(build, tmp_path):
    app = fake_app(tmp_path / "dist" / "SubtitleMaker", "exit 3")

    assert build.self_check(app, tmp_path / "clip.flac", "tiny", tmp_path / "r.txt") == 3


# --- the whole driver, with the slow parts stood in for ---------------------------------------


@pytest.fixture
def driver(build, tmp_path, monkeypatch):
    """`main` with PyInstaller and the packaging tools replaced, recording what was called."""

    calls = []
    app = tmp_path / "built"
    app.mkdir()

    monkeypatch.setattr(build, "make_icons", lambda *a: None)
    monkeypatch.setattr(build, "render_png", lambda svg, size: PNG)
    monkeypatch.setattr(build, "run_pyinstaller", lambda *a: calls.append("pyinstaller") or app)

    def maker(name, suffix):
        def make(built, out, version, tag, *rest):
            calls.append(name)
            path = out / build.artifact_name(version, tag, suffix)
            path.write_bytes(name.encode())

            return path

        return make

    monkeypatch.setattr(build, "package_tar", maker("tar", ".tar.gz"))
    monkeypatch.setattr(build, "package_zip", maker("zip", ".zip"))
    monkeypatch.setattr(build, "package_appimage", maker("appimage", ".AppImage"))
    monkeypatch.setattr(build, "package_dmg", maker("dmg", ".dmg"))

    def run(system, machine, *args):
        monkeypatch.setattr(build.platform, "system", lambda: system)
        monkeypatch.setattr(build.platform, "machine", lambda: machine)

        return build.main(["--out", str(tmp_path / "out"), "--work", str(tmp_path / "work"), *args])

    return type("Driver", (), {"run": staticmethod(run), "calls": calls, "out": tmp_path / "out"})


def names(driver):
    return sorted(p.name for p in driver.out.iterdir())


def test_linux_makes_a_tar_and_an_appimage_and_checksums_for_both(driver, tmp_path):
    tool = tmp_path / "appimagetool"
    tool.write_text("")

    assert driver.run("Linux", "x86_64", "--appimagetool", str(tool)) == 0

    assert driver.calls == ["pyinstaller", "tar", "appimage"]
    assert names(driver) == [
        "SHA256SUMS",
        f"SubtitleMaker-{__version__}-linux-x86_64.AppImage",
        f"SubtitleMaker-{__version__}-linux-x86_64.tar.gz",
    ]
    sums = (driver.out / "SHA256SUMS").read_text()
    assert "AppImage" in sums and "tar.gz" in sums


def test_linux_without_the_tool_still_makes_the_tar(driver, monkeypatch, capsys):
    monkeypatch.setattr(driver_module(driver), "shutil", _NoTool())

    assert driver.run("Linux", "x86_64") == 0

    assert driver.calls == ["pyinstaller", "tar"]
    assert "no AppImage made" in capsys.readouterr().err


def driver_module(driver):
    return sys.modules["subtitlemaker_build"]


class _NoTool:
    """`shutil` with `which` finding nothing."""

    def __getattr__(self, name):
        return getattr(shutil, name)

    @staticmethod
    def which(name):
        return None


def test_windows_makes_a_zip(driver):
    assert driver.run("Windows", "AMD64") == 0

    assert driver.calls == ["pyinstaller", "zip"]
    assert f"SubtitleMaker-{__version__}-windows-x64.zip" in names(driver)


@pytest.mark.parametrize("machine", ["arm64", "x86_64"])
def test_macos_makes_a_dmg_for_each_processor(driver, machine):
    assert driver.run("Darwin", machine) == 0

    assert driver.calls == ["pyinstaller", "dmg"]
    assert f"SubtitleMaker-{__version__}-macos-{machine}.dmg" in names(driver)


@posix_only
def test_a_failing_self_check_stops_before_anything_is_packaged(
    driver, build, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(build, "self_check", lambda *a: 1)

    code = driver.run("Linux", "x86_64", "--self-check-audio", str(tmp_path / "clip.flac"))

    assert code == 1
    assert driver.calls == ["pyinstaller"]  # no tar, no AppImage
    assert list(driver.out.iterdir()) == []  # the folder exists, with nothing in it
    assert "nothing was packaged" in capsys.readouterr().err


def test_a_passing_self_check_lets_the_build_go_on(driver, build, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(build, "self_check", lambda *a: seen.append(a) or 0)

    assert driver.run("Windows", "AMD64", "--self-check-audio", str(tmp_path / "c.flac")) == 0

    assert len(seen) == 1 and seen[0][2] == "tiny"
    assert driver.calls == ["pyinstaller", "zip"]


def test_an_unsupported_system_is_refused(driver):
    with pytest.raises(RuntimeError, match="unsupported system"):
        driver.run("FreeBSD", "amd64")


@posix_only
def test_a_pinned_runtime_is_handed_to_the_tool_and_none_is_not_invented(build, tmp_path):
    app = fake_app(tmp_path / "dist" / "SubtitleMaker")
    record = tmp_path / "args.txt"
    tool = tmp_path / "appimagetool"
    tool.write_text(f'#!/bin/sh\necho "$@" > {record}\ntouch "$(for a; do :; done; echo $a)"\n')
    tool.chmod(0o755)
    (tmp_path / "out").mkdir()
    runtime = tmp_path / "runtime-x86_64"
    runtime.write_bytes(b"runtime")

    build.package_appimage(
        app, tmp_path / "out", "0.3.0", "linux-x86_64", tool, tmp_path, PNG, runtime
    )
    with_runtime = record.read_text().split()

    build.package_appimage(app, tmp_path / "out", "0.3.0", "linux-x86_64", tool, tmp_path, PNG)
    without = record.read_text().split()

    assert with_runtime[:2] == ["--runtime-file", str(runtime)]
    assert "--runtime-file" not in without  # the tool downloads its own, as before


def test_the_driver_passes_the_runtime_on(driver, tmp_path, monkeypatch, build):
    seen = []
    monkeypatch.setattr(build, "package_appimage", lambda *a: seen.append(a) or tmp_path / "x")
    tool = tmp_path / "appimagetool"
    tool.write_text("")
    runtime = tmp_path / "runtime"
    (tmp_path / "x").write_text("")

    driver.run("Linux", "x86_64", "--appimagetool", str(tool), "--appimage-runtime", str(runtime))

    assert seen[0][-1] == runtime


# --- a self-check that never ends must not hold up the build ----------------------------------


def test_a_self_check_that_hangs_fails_the_build_instead_of_waiting(build, monkeypatch, tmp_path):
    def hang(command, **kwargs):
        assert kwargs["timeout"] == build.SELF_CHECK_TIMEOUT
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(build.subprocess, "run", hang)
    monkeypatch.setattr(build, "executable", lambda built: built)

    code = build.self_check(tmp_path, tmp_path / "a.flac", "tiny", tmp_path / "report.txt")

    assert code == 1


def test_the_packaged_entry_point_exits_at_once_after_a_self_check(tmp_path):
    # The macOS app finished its checks and then never exited. Run the real entry point
    # (without audio, so no model is needed) and require a prompt exit with the report written.
    pytest.importorskip("PySide6")

    report = tmp_path / "report.txt"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "packaging" / "app_entry.py"),
            "--self-check",
            "--report",
            str(report),
        ],
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode in (0, 1), result.stderr
    assert (
        report.read_text(encoding="utf-8")
        .rstrip()
        .endswith(("self-check passed", "self-check FAILED"))
    )
    assert "self-check" in result.stdout


def test_the_entry_point_copes_with_no_console_streams(monkeypatch):
    # A windowed Windows app has sys.stdout = None. Flushing it raised, and the packaged
    # app answered with a modal error box, which hung the Windows build.
    spec = importlib.util.spec_from_file_location(
        "subtitlemaker_app_entry", ROOT / "packaging" / "app_entry.py"
    )
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)

    left = []
    monkeypatch.setattr(entry, "main", lambda: 3)
    monkeypatch.setattr(entry.os, "_exit", left.append)
    monkeypatch.setattr(entry.sys, "argv", ["SubtitleMaker.exe", "--self-check"])
    monkeypatch.setattr(entry.sys, "stdout", None)
    monkeypatch.setattr(entry.sys, "stderr", None)

    entry.run()

    assert left == [3]
