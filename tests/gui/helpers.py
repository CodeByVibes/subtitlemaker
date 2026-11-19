"""Helpers shared by the GUI tests."""

from pathlib import Path


def media(folder: Path, *names: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []

    for name in names:
        path = folder / name
        path.write_bytes(b"")  # never decoded: the model is fake
        paths.append(path)

    return paths
