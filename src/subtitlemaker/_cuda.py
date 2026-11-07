"""CUDA library setup for CTranslate2.

CTranslate2 needs the CUDA 12 runtime libraries (cuBLAS and cuDNN 9). They
can come from the system, or from the pip packages installed by the
`subtitlemaker[cuda]` extra. The dynamic loader only searches
LD_LIBRARY_PATH as it was when the process started, so instead of
re-executing the interpreter we load the pip copies ourselves, early, with
global visibility. CTranslate2 later asks for them by name and the loader
hands back the copies already in memory.
"""

import ctypes
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# Load order matters: cuBLAS needs cuBLASLt, cuDNN's front library goes first.
_PACKAGES = (
    ("nvidia.cublas", ("libcublasLt.so.12", "libcublas.so.12")),
    ("nvidia.cudnn", ("libcudnn.so.9",)),
)

_loaded: bool | None = None


def _package_lib_dir(package: str) -> Path | None:
    """Directory holding the shared libraries of an nvidia-* pip package."""

    try:
        module = __import__(package + ".lib", fromlist=["lib"])

    except ImportError:
        return None

    paths = list(getattr(module, "__path__", []))

    return Path(paths[0]) if paths else None


def preload_cuda_libs() -> bool:
    """
    Load cuBLAS and cuDNN from the pip nvidia-* packages, if installed.

    Returns True if the libraries are available this way, False if not
    (not on Linux, or the `[cuda]` extra is not installed). Safe to call
    repeatedly; it never raises for missing packages. A False result does
    not mean CUDA is unusable, system libraries may still be found.
    """

    global _loaded

    if _loaded is not None:
        return _loaded

    if not sys.platform.startswith("linux"):
        _loaded = False
        return _loaded

    found_any = False

    for package, libraries in _PACKAGES:

        directory = _package_lib_dir(package)

        if directory is None:
            log.debug("%s is not installed", package)
            continue

        for library in libraries:

            path = directory / library

            if not path.exists():
                log.debug("%s not found", path)
                continue

            try:
                ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)

            except OSError as e:
                log.debug("couldn't load %s: %s", path, e)
                continue

            log.debug("preloaded %s", path)
            found_any = True

    _loaded = found_any

    return _loaded
