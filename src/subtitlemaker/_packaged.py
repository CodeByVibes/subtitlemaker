"""The standalone app builds.

The downloadable apps (built with PyInstaller, see packaging/) run on the CPU
only: the CUDA libraries alone would add about 1.3 GB. An app on a machine
with an NVIDIA GPU must still never try the GPU. With `device = auto` it would
choose the big GPU model (large-v3), download its 2.9 GB, and only then find
that CUDA cannot start.
"""

import os
import sys

# Set to 1 to let a packaged app try CUDA anyway (it needs CUDA 12 libraries on the system).
USE_CUDA_VARIABLE = "SUBTITLEMAKER_USE_CUDA"

PIP_HINT = "pip install 'subtitlemaker[gui,cuda]'"

CPU_ONLY_NOTE = (
    "This is the CPU-only app build, which has no CUDA libraries. For NVIDIA GPU "
    f"support, install SubtitleMaker with pip instead: {PIP_HINT}"
)


def is_packaged_app() -> bool:
    """True when running as one of the standalone apps rather than from Python."""

    return bool(getattr(sys, "frozen", False))


def cpu_only_build() -> bool:
    """True when the GPU must not be used: a packaged app, unless told otherwise."""

    return is_packaged_app() and os.environ.get(USE_CUDA_VARIABLE) != "1"
