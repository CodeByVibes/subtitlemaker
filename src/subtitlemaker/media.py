"""Media file inspection."""

from pathlib import Path

import av


def get_duration(filename: str | Path) -> float:
    """Get media duration using PyAV."""

    container = av.open(filename)

    try:

        if container.duration is not None:
            return container.duration / av.time_base

        # Fallback
        for stream in container.streams:

            if (
                stream.duration is not None
                and stream.time_base is not None
            ):
                return float(
                    stream.duration
                    * stream.time_base
                )

        return 0.0

    finally:
        container.close()


# Containers and codecs people commonly want subtitles for. Anything else
# can still be given explicitly as a file; this only limits what is picked
# up when a folder is scanned.
MEDIA_EXTENSIONS = frozenset(
    {
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts", ".flv", ".wmv",
        ".mpg", ".mpeg", ".3gp", ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg",
        ".oga", ".opus", ".wma", ".mka",
    }
)  # fmt: skip


def find_media(directory: Path, recursive: bool = False) -> list[Path]:
    """
    The media files in `directory`, sorted by path.

    Skips macOS "AppleDouble" companions (`._name.mp4`), which have a media
    extension but are metadata, not media. Raises `OSError` if the folder
    cannot be read.
    """

    candidates = directory.rglob("*") if recursive else directory.iterdir()

    return sorted(
        path
        for path in candidates
        if path.suffix.lower() in MEDIA_EXTENSIONS
        and not path.name.startswith("._")
        and path.is_file()
    )
