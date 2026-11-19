"""What the packaged app runs. (The installed command is `subtitlemaker-gui`.)"""

import os
import sys

from subtitlemaker.gui import main


def run() -> int:
    code = main()

    # The macOS build finished its self-check ("self-check passed", report written) and then
    # never exited: something in the interpreter's shutdown (native threads of the speech
    # libraries) waited forever. The result is already out, so leave at once.
    if "--self-check" in sys.argv:
        # A windowed app on Windows has no console: both streams are None there, and an
        # exception in this app opens a modal error box that nobody can click on a CI runner.
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                stream.flush()

        os._exit(code)

    return code


if __name__ == "__main__":
    raise SystemExit(run())
