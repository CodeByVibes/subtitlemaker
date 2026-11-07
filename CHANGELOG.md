# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Subtitle files are written to a temporary file and moved into place when complete, so a crash or full disk can no longer leave a truncated file that `--skip-existing` would treat as done. An existing file stays untouched if writing fails.
- A config file with a section that is not a table (`style = 5`), an unreadable config file, or a folder given to `--config` now gives a usage error with the file name instead of a traceback.
- `nan` and `inf` are rejected for the style values (`--max-cps nan` used to be accepted).
- Ctrl-C stops with a short "interrupted" message and exit code 130 instead of a long traceback.
- When the GPU cannot be used and the CPU takes over, a model or compute type you chose yourself is kept. Only values left on auto are swapped for CPU defaults. A chosen compute type the CPU cannot run is reported as such.
- Folder scans skip macOS `._name.mp4` companion files, and an unreadable folder is reported as an error (exit code 1) while the other inputs still run.
- `-v` now shows the traceback of a failed file. The log formatter used to drop it, so `-v` output was no use in a bug report.
- A model that cannot be downloaded or loaded (no internet on first use, a mistyped repo id, a bad path) now ends in a short error with a hint instead of a traceback. A name such as `models/mine`, where `models` is a local folder, is reported as "model path not found" rather than looked up on Hugging Face.

### Changed
- `-l he,en` only switches on per-segment language detection, exactly like `-m`; it never limited detection to the listed languages. The log line, `--help` and the README now say so.
- `--help` and `--version` no longer load faster-whisper and ctranslate2, so they are faster and still work if those libraries are broken.

## [0.1.2] - 2026-11-07

### Fixed
- A single word longer than the line limit (a URL, or any Chinese or Japanese sentence, which has no spaces) produced a subtitle starting with an empty line. In WebVTT that made ffmpeg read the whole file as empty. The word is now split in half, or kept whole when only one line is allowed.
- `-o` (or `-d`) pointing at an input file would overwrite that input, for example `subtitlemaker talk.mp4 -o talk.mp4` replaced the video with subtitles. This is now refused as a usage error before anything runs. Output collisions are also compared by resolved path.

## [0.1.1] - 2026-11-07

### Fixed
- A subtitle could contain words that are spoken many seconds apart. Whisper sometimes puts words on either side of a long silence (a laugh track, music) into one segment, and the subtitle then showed the later words long before they were spoken. On a two minute sitcom clip, four subtitles were affected, the worst with an 11.6 second gap. A long silence between two words now starts a new subtitle.

### Added
- `--max-pause` (and `max_pause` in the `[style]` section of the config file): how much silence between two words starts a new subtitle. The default is 1.0 seconds. This only applies with word timestamps, which are on by default.

## [0.1.0] - 2026-11-07

First public release. It grew out of a single prototype script.

### Added
- Subtitle output as SRT, WebVTT and plain text (`-f srt,vtt,txt`).
- Batch mode: several files and folders (`-r` to recurse), `--output-dir`, `--skip-existing`. The model is loaded once, and a file that fails does not stop the others.
- CPU support. `--device auto|cuda|cpu` falls back to the CPU when no usable GPU is found, with a warning.
- `--model` to choose the Whisper model (size, Hugging Face repo id or local path) and `--compute-type`. The default is `large-v3` on a GPU and `small` on the CPU.
- Word timestamps (`--word-timestamps`, on by default): subtitles start at the first word and end at the last, and long sentences are split at sentence ends and real word times.
- Subtitle style options (`--max-line-length`, `--max-lines`, `--max-cps`, `--min-duration`, `--max-duration`, `--min-gap`) and a TOML config file.
- `--quiet` and `--verbose`, `--version`, and a progress bar. Messages go to stderr.
- Optional `cuda` extra that installs the CUDA 12 libraries from PyPI.

### Changed
- The default task is `transcribe` (subtitles in the spoken language). The prototype translated to English by default; use `-t translate` for that.
- Subtitles are no longer shifted later to make room for readability padding. Padding only extends a subtitle into free time.
- `--max-lines` accepts 1 or 2.

### Fixed
- A line could be one character longer than the maximum.
- The first subtitle was delayed by the minimum gap.
- The GPU libraries are loaded without re-launching the Python process, so `python -m subtitlemaker` works.
- A GPU without the CUDA 12 libraries no longer ends in a traceback in the middle of a run.

[Unreleased]: https://github.com/CodeByVibes/subtitlemaker/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/CodeByVibes/subtitlemaker/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/CodeByVibes/subtitlemaker/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/CodeByVibes/subtitlemaker/releases/tag/v0.1.0
