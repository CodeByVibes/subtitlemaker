"""Deciding what to process and where the results go.

Pure path logic with no command line parsing, so the command line and the
desktop app can share it.
"""

import logging
from collections.abc import Sequence
from pathlib import Path

from .formats import FORMATS, output_path
from .log import LOGGER_NAME
from .media import find_media

log = logging.getLogger(LOGGER_NAME)


def expand_inputs(inputs: Sequence[str | Path], recursive: bool) -> tuple[list[Path], list[str]]:
    """
    Turn a list of files and folders into a list of media files.

    Folders contribute the media files in them (and in sub folders with
    `recursive`). Returns `(files, problems)`, where `problems` holds a
    message for each input that does not exist or cannot be read;
    duplicates are dropped.
    """

    files = []
    problems = []
    seen = set()

    for raw in inputs:

        path = Path(raw)

        if path.is_dir():

            try:
                found = find_media(path, recursive)

            except OSError as e:
                problems.append(f"couldn't read folder {path}: {e.strerror or e}")
                continue

            if not found:
                log.warning("no media files found in %s", path)

        elif path.exists():
            found = [path]

        else:
            problems.append(f"input file does not exist: {path}")
            continue

        for file in found:

            key = file.resolve()

            if key not in seen:
                seen.add(key)
                files.append(file)

    return files, problems


def plan_outputs(
    input_file: Path,
    formats: Sequence[str],
    output: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Path]:
    """The `{format: path}` files to write for one input."""

    if output:

        base = Path(output)

        # One format: the name is used exactly as given.
        if len(formats) == 1:
            return {formats[0]: base}

        return {name: output_path(base, name) for name in formats}

    folder = Path(output_dir) if output_dir else input_file.parent

    return {
        name: folder / f"{input_file.stem}.{FORMATS[name].extension}"
        for name in formats
    }


def plan_all_outputs(
    files: Sequence[Path],
    formats: Sequence[str],
    output: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[Path, dict[str, Path]]:
    """
    Decide where every input's outputs go: `{input file: {format: path}}`.

    Raises `ValueError` (with a user-facing message) if an output would
    overwrite an input, or two inputs would write the same file.
    """

    if output and len(files) > 1:
        raise ValueError(
            "-o/--output can only be used with a single input file; "
            "use -d/--output-dir for several"
        )

    plan = {file: plan_outputs(file, formats, output, output_dir) for file in files}

    owners: dict[Path, Path] = {}
    input_paths = {file.resolve(): file for file in files}

    for file, outputs in plan.items():

        for path in outputs.values():

            key = path.resolve()

            if key in input_paths:
                raise ValueError(
                    f"the output {path} is the input file {input_paths[key]}; "
                    f"it would be overwritten"
                )

            if key in owners:
                raise ValueError(
                    f"{owners[key]} and {file} would both write {path}; "
                    f"use separate output folders"
                )

            owners[key] = file

    return plan
