"""What the packaged app runs. (The installed command is `subtitlemaker-gui`.)"""

from subtitlemaker.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
