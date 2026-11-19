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
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)

    return code


if __name__ == "__main__":
    raise SystemExit(run())
