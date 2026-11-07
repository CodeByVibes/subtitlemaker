"""Write a file so that it is either complete or not there at all."""

import contextlib
import os
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO


@contextlib.contextmanager
def atomic_open(path: str | Path) -> Iterator[TextIO]:
    """
    Open `path` for writing text (UTF-8), replacing it only on success.

    The text goes to a temporary file in the same folder, which is moved
    over `path` when the `with` block ends without an error. A crash, a
    full disk or an exception mid-write therefore never leaves a truncated
    subtitle file behind (which `--skip-existing` would trust), and an
    existing file stays as it was.
    """

    path = Path(path)

    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yield f

        _copy_mode(path, temp_name)
        os.replace(temp_name, path)

    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)

        raise


def _copy_mode(path: Path, temp_name: str) -> None:
    # mkstemp makes the file private (0600); give it the permissions a plain
    # open() would have: those of the file being replaced, or the umask default.
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)

    except OSError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask

    os.chmod(temp_name, mode)
