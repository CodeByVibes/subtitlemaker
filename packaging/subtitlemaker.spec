# PyInstaller spec for the SubtitleMaker desktop app. Run it through packaging/build.py,
# which sets the environment variables read here and does the per-system packaging.
#
# The build environment must NOT have the `cuda` extra: the app is CPU only, and the
# CUDA libraries alone would add about 1.3 GB.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is provided by PyInstaller)
VERSION = os.environ["SUBTITLEMAKER_VERSION"]
ICON = os.environ.get("SUBTITLEMAKER_ICON") or None  # .ico on Windows, .icns on macOS

# Data the code reads at run time and PyInstaller cannot see from the imports:
# the app icon, and faster-whisper's voice activity model (silero_vad_*.onnx).
datas = collect_data_files("subtitlemaker") + collect_data_files("faster_whisper")

analysis = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "app_entry.py")],
    pathex=[],
    binaries=[],
    datas=datas,
    # The code never imports QtSvg, but Qt draws the SVG icon through its plugin, which
    # PyInstaller only bundles for modules it finds imported.
    hiddenimports=["PySide6.QtSvg"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "pytest",
        "IPython",
        "matplotlib",
        "PIL",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtNetwork",
        "PySide6.QtSql",
        "PySide6.QtTest",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="SubtitleMaker",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # a window, not a terminal program (stdout is lost: use --report)
    icon=ICON,
)

collected = COLLECT(  # noqa: F821
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="SubtitleMaker",
)

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        collected,
        name="SubtitleMaker.app",
        icon=ICON,
        bundle_identifier="io.github.codebyvibes.subtitlemaker",
        version=VERSION,
        info_plist={
            "CFBundleName": "SubtitleMaker",
            "CFBundleDisplayName": "SubtitleMaker",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "MIT licence",
        },
    )
