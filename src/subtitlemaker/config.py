"""Default settings. (Becomes dataclasses in a later step.)"""

# Whisper model
MODEL = "large-v3"
DEVICE = "cuda"
COMPUTE_TYPE = "float16"

# Subtitle layout
MAX_LINE_LENGTH = 42       # Maximum characters per line
MAX_LINES = 2              # Maximum number of lines

# Subtitle readability
MAX_CPS = 20               # Maximum characters per second
MIN_DURATION = 1.0         # Minimum subtitle duration
MAX_DURATION = 7.0         # Maximum subtitle duration
MIN_GAP = 0.05             # Minimum gap between subtitles

# Whisper
VAD_FILTER = True
CONDITION_ON_PREVIOUS_TEXT = True
