"""Qt tests run without a display: no window ever appears on the developer's screen."""

import os

# Assigned, not `setdefault`: a desktop session often exports its own
# QT_QPA_PLATFORM (e.g. "wayland;xcb"), and the tests must not open real windows.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
