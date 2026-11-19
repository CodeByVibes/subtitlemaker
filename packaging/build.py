"""Build the standalone SubtitleMaker app for this system.

    python packaging/build.py [--out DIR] [--work DIR] [--self-check-audio FILE]
                              [--appimagetool PATH] [--appimage-runtime FILE]

Run it in an environment that has the `gui` extra and the `build` group but not the
`cuda` extra (see CONTRIBUTING.md). It needs PySide6 (to draw the icon) and
PyInstaller. The result is a set of files in `--out`, with a SHA256SUMS file:

    Linux    SubtitleMaker-VERSION-linux-x86_64.tar.gz  (and an .AppImage if appimagetool is given)
    Windows  SubtitleMaker-VERSION-windows-x64.zip
    macOS    SubtitleMaker-VERSION-macos-arm64.dmg (or -x86_64)

Only the parts that run on every system are here at the top; the per-system parts
call tools that exist only there (hdiutil, appimagetool).
"""

import argparse
import hashlib
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
APP_NAME = "SubtitleMaker"

# --- naming ---------------------------------------------------------------------------------


def app_version(root: Path = ROOT) -> str:
    """The version, from the one place it is defined."""

    text = (root / "src" / "subtitlemaker" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)

    if match is None:
        raise RuntimeError("no __version__ in src/subtitlemaker/__init__.py")

    return match.group(1)


def platform_tag(system: str | None = None, machine: str | None = None) -> str:
    """`linux-x86_64`, `windows-x64`, `macos-arm64` or `macos-x86_64`."""

    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()

    if machine in ("amd64", "x86_64", "x64"):
        machine = "x86_64"

    elif machine in ("arm64", "aarch64"):
        machine = "arm64" if system == "darwin" else "aarch64"

    if system == "windows":
        return "windows-x64" if machine == "x86_64" else f"windows-{machine}"

    if system == "darwin":
        return f"macos-{machine}"

    if system == "linux":
        return f"linux-{machine}"

    raise RuntimeError(f"unsupported system: {system}")


def artifact_name(version: str, tag: str, suffix: str) -> str:
    """The file name of a download, e.g. `SubtitleMaker-0.2.0-linux-x86_64.tar.gz`."""

    return f"{APP_NAME}-{version}-{tag}{suffix}"


# --- icons -----------------------------------------------------------------------------------


def render_png(svg: Path, size: int) -> bytes:
    """The SVG drawn as a `size` by `size` PNG (needs PySide6)."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 (kept alive)

    renderer = QSvgRenderer(str(svg))

    if not renderer.isValid():
        raise RuntimeError(f"not a valid SVG: {svg}")

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")

    return bytes(data.data())


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# ICNS entry types that hold PNG data, by pixel size.
ICNS_TYPES = {16: b"icp4", 32: b"icp5", 64: b"icp6", 128: b"ic07", 256: b"ic08", 512: b"ic09", 1024: b"ic10"}


def ico_bytes(pngs: Mapping[int, bytes]) -> bytes:
    """A Windows icon holding these PNGs (`{size: png data}`, each 256 pixels or smaller)."""

    if not pngs:
        raise ValueError("no images")

    sizes = sorted(pngs)

    if sizes[-1] > 256:
        raise ValueError("an ICO image is at most 256 pixels")

    header = struct.pack("<HHH", 0, 1, len(sizes))
    entries = b""
    images = b""
    offset = len(header) + 16 * len(sizes)

    for size in sizes:
        data = pngs[size]
        stored = 0 if size == 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", stored, stored, 0, 0, 1, 32, len(data), offset)
        images += data
        offset += len(data)

    return header + entries + images


def icns_bytes(pngs: Mapping[int, bytes]) -> bytes:
    """A macOS icon holding these PNGs (`{size: png data}`, sizes from ICNS_TYPES)."""

    unknown = sorted(set(pngs) - set(ICNS_TYPES))

    if unknown or not pngs:
        raise ValueError(f"sizes not usable in an ICNS: {unknown or 'none given'}")

    body = b"".join(
        ICNS_TYPES[size] + struct.pack(">I", 8 + len(pngs[size])) + pngs[size]
        for size in sorted(pngs)
    )

    return b"icns" + struct.pack(">I", 8 + len(body)) + body


def make_icons(svg: Path, folder: Path, system: str) -> Path | None:
    """The icon file PyInstaller wants on this system (`.ico` or `.icns`), or None."""

    folder.mkdir(parents=True, exist_ok=True)

    if system == "Windows":
        path = folder / "SubtitleMaker.ico"
        path.write_bytes(ico_bytes({size: render_png(svg, size) for size in ICO_SIZES}))

        return path

    if system == "Darwin":
        path = folder / "SubtitleMaker.icns"
        path.write_bytes(icns_bytes({size: render_png(svg, size) for size in ICNS_TYPES}))

        return path

    return None


# --- files ------------------------------------------------------------------------------------


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def write_checksums(files: Iterable[Path], target: Path) -> Path:
    """`SHA256SUMS`: one `hash  name` line per file, sorted by name (checkable with `sha256sum -c`)."""

    lines = [f"{sha256(path)}  {path.name}" for path in sorted(files, key=lambda p: p.name)]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return target


# --- building ------------------------------------------------------------------------------------


def run_pyinstaller(version: str, icon: Path | None, dist: Path, work: Path) -> Path:
    """Run PyInstaller on the spec. Returns what it made (the app folder, or the .app)."""

    import PyInstaller.__main__

    env = {"SUBTITLEMAKER_VERSION": version, "SUBTITLEMAKER_ICON": str(icon) if icon else ""}
    os.environ.update(env)

    PyInstaller.__main__.run(
        [
            str(PACKAGING / "subtitlemaker.spec"),
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
        ]
    )

    built = dist / ("SubtitleMaker.app" if platform.system() == "Darwin" else "SubtitleMaker")

    if not built.exists():
        raise RuntimeError(f"PyInstaller did not make {built}")

    return built


def executable(built: Path) -> Path:
    """The program inside what PyInstaller made."""

    if platform.system() == "Darwin":
        return built / "Contents" / "MacOS" / APP_NAME

    return built / (APP_NAME + (".exe" if platform.system() == "Windows" else ""))


def package_tar(built: Path, out: Path, version: str, tag: str) -> Path:
    """A .tar.gz of the app folder."""

    target = out / artifact_name(version, tag, ".tar.gz")

    with tarfile.open(target, "w:gz") as archive:
        archive.add(built, arcname=APP_NAME)

    return target


def package_zip(built: Path, out: Path, version: str, tag: str) -> Path:
    """A .zip of the app folder."""

    target = out / artifact_name(version, tag, ".zip")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(built.rglob("*")):
            if path.is_file():
                archive.write(path, Path(APP_NAME) / path.relative_to(built))

    return target


APPRUN = """#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/SubtitleMaker/SubtitleMaker" "$@"
"""


def desktop_entry_for_appimage(version: str) -> str:
    """The desktop entry from `packaging/`, launching the app by the name AppRun finds it under."""

    text = (PACKAGING / "subtitlemaker.desktop").read_text(encoding="utf-8")

    if "Exec=subtitlemaker-gui" not in text:
        raise RuntimeError("packaging/subtitlemaker.desktop no longer runs subtitlemaker-gui")

    text = text.replace("Exec=subtitlemaker-gui", "Exec=SubtitleMaker")

    return text.rstrip("\n") + f"\nX-AppImage-Version={version}\n"


def make_appdir(built: Path, appdir: Path, version: str, icon_png: bytes) -> Path:
    """The folder appimagetool turns into an AppImage: the app, AppRun, the entry and the icon."""

    if appdir.exists():
        shutil.rmtree(appdir)

    shutil.copytree(built, appdir / "usr" / "bin" / APP_NAME, symlinks=True)

    apprun = appdir / "AppRun"
    apprun.write_text(APPRUN, encoding="utf-8")
    apprun.chmod(0o755)

    (appdir / "subtitlemaker.desktop").write_text(desktop_entry_for_appimage(version), encoding="utf-8")
    (appdir / "subtitlemaker.png").write_bytes(icon_png)
    (appdir / ".DirIcon").symlink_to("subtitlemaker.png")

    return appdir


def package_appimage(
    built: Path,
    out: Path,
    version: str,
    tag: str,
    tool: Path,
    work: Path,
    icon_png: bytes,
    runtime: Path | None = None,
) -> Path:
    """
    An AppImage of the app, made with `tool` (appimagetool).

    Without `runtime` the tool downloads its runtime (the small program at the front
    of every AppImage) from the internet, always the latest. Pass a pinned file for a
    build that does not depend on that.
    """

    appdir = make_appdir(built, work / "SubtitleMaker.AppDir", version, icon_png)
    target = out / artifact_name(version, tag, ".AppImage")

    # ARCH is required by the tool. APPIMAGE_EXTRACT_AND_RUN makes the tool, when it is itself
    # an AppImage (as the downloaded one is), run without FUSE, which a build machine often
    # lacks; a tool installed as a normal program ignores it.
    env = dict(os.environ, ARCH=platform.machine(), APPIMAGE_EXTRACT_AND_RUN="1")

    command = [str(tool)]

    if runtime is not None:
        command += ["--runtime-file", str(runtime)]

    subprocess.run([*command, str(appdir), str(target)], check=True, env=env)

    return target


def package_dmg(app: Path, out: Path, version: str, tag: str, work: Path) -> Path:
    """A disk image holding the .app and a link to Applications (macOS only: needs hdiutil)."""

    staging = work / "dmg"

    if staging.exists():
        shutil.rmtree(staging)

    staging.mkdir(parents=True)
    shutil.copytree(app, staging / app.name, symlinks=True)  # keeps the framework symlinks
    (staging / "Applications").symlink_to("/Applications")

    target = out / artifact_name(version, tag, ".dmg")

    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            str(staging),
            "-ov",
            "-format",
            "UDZO",
            str(target),
        ],
        check=True,
    )

    return target


def self_check(built: Path, audio: Path, model: str, report: Path) -> int:
    """Run the built app's own checks (including a real transcription). Returns its exit code."""

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")

    result = subprocess.run(
        [
            str(executable(built)),
            "--self-check",
            "--audio",
            str(audio),
            "--model",
            model,
            "--report",
            str(report),
        ],
        env=env,
    )

    # A windowed app on Windows has no console: its report is in the file.
    if report.is_file():
        print(report.read_text(encoding="utf-8"))

    return result.returncode


def main(argv: list[str] | None = None) -> int:

    parser = argparse.ArgumentParser(description="Build the standalone SubtitleMaker app.")
    parser.add_argument("--out", type=Path, default=Path("/tmp/subtitlemaker-out"))
    parser.add_argument("--work", type=Path, default=Path("/tmp/subtitlemaker-work"))
    parser.add_argument(
        "--self-check-audio",
        type=Path,
        metavar="FILE",
        help="run the built app's self-check on this clip before packaging; fail the build if it fails",
    )
    parser.add_argument("--model", default="tiny", help="model for the self-check (default: tiny)")
    parser.add_argument(
        "--appimage-runtime",
        type=Path,
        metavar="FILE",
        help="Linux: the AppImage runtime file to use (default: the tool downloads the latest)",
    )
    parser.add_argument(
        "--appimagetool",
        metavar="PATH",
        help="Linux: make an AppImage with this tool ('auto' uses appimagetool from PATH if present)",
        default="auto",
    )
    args = parser.parse_args(argv)

    version = app_version()
    tag = platform_tag()
    system = platform.system()
    svg = ROOT / "src" / "subtitlemaker" / "gui" / "resources" / "icon.svg"

    args.out.mkdir(parents=True, exist_ok=True)

    icon = make_icons(svg, args.work / "icons", system)
    built = run_pyinstaller(version, icon, args.work / "dist", args.work / "build")

    if args.self_check_audio is not None:
        print("Checking the built app ...", flush=True)

        if self_check(built, args.self_check_audio, args.model, args.work / "self-check.txt") != 0:
            print("The built app failed its self-check: nothing was packaged.", file=sys.stderr)
            return 1

    files: list[Path] = []

    if system == "Linux":
        files.append(package_tar(built, args.out, version, tag))

        tool = shutil.which("appimagetool") if args.appimagetool == "auto" else args.appimagetool

        if tool:
            files.append(
                package_appimage(
                    built,
                    args.out,
                    version,
                    tag,
                    Path(tool),
                    args.work,
                    render_png(svg, 256),
                    args.appimage_runtime,
                )
            )

        elif args.appimagetool != "auto":
            raise SystemExit(f"appimagetool not found: {args.appimagetool}")

        else:
            print("appimagetool not found: no AppImage made", file=sys.stderr)

    elif system == "Windows":
        files.append(package_zip(built, args.out, version, tag))

    elif system == "Darwin":
        files.append(package_dmg(built, args.out, version, tag, args.work))

    else:
        raise SystemExit(f"cannot package for {system}")

    files.append(write_checksums(files, args.out / "SHA256SUMS"))

    for path in files:
        print(f"{path.stat().st_size / 1e6:8.1f} MB  {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
