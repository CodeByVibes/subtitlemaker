# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `--prompt TEXT` (and `initial_prompt` in the `[model]` section of the config file): text Whisper continues from. When a recording starts mid-sentence, Whisper can write minutes of text with no punctuation or capitals; a punctuated prompt fixes that. On three such 5-minute clips of a sitcom, punctuation went from 0–7% of words to 20–27%, the same as the rest of the episode. Off by default: on a Swedish programme with broadcast subtitles to compare against, prompts changed the word error rate by −1.4 to +6.4 points, with no prompt reliably better.
- A warning when a transcript has almost no punctuation (under one mark per 50 words, and at least 150 words), suggesting `--prompt`. It fired on all three unpunctuated clips and on none of ten normal ones.
- `--linger` (and `linger` in the `[style]` section of the config file): a subtitle stays up this long after its speech ends, if the time is free. The default is 0.5 seconds; before, a subtitle could vanish the instant the last word ended.
- `--close-gap` (and `close_gap`): when the gap to the next subtitle would be shorter than this, the subtitle stays up until `--min-gap` before the next one, so text doesn't flicker off and on between lines of dialogue. The default is 0.5 seconds. `--max-duration` is still a hard limit. On four 5-minute TV clips this removed 40 of 42 gaps between 0.06 and 0.5 s (the other two cues are at the 7 s limit) and cut subtitles faster than 20 characters per second from 36 to 25. Setting both to 0 turns them off.

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
- For English and Swedish, the first line no longer ends on an article, preposition or conjunction when a better break exists ("Either you work for the system" / "or you make the system work for you."). In every language, two capitalised words in a row are kept on one line ("Andrea Russell"). The language is the detected or given one, English with `-t translate`, and none with `-m`. On the sitcom episode and two Swedish clips this changed 18 of 491 subtitles.
- A subtitle holds at most two speakers of dialogue written with dashes, each on a line of their own. A third speaker, or a second one when either speaker's words don't fit on one line, starts a new subtitle ("–Absolut. –Varsågod." used to share a subtitle with a third "–Varsågod."). The exception is very quick exchanges: if the subtitle before the cut would get less than `--min-duration` of speech, the speakers stay together rather than flash past. On two 5-minute Swedish clips, subtitles with three or more speakers went from 9 to 1.
- Better line breaks. In dialogue, each speaker gets their own line ("–Ja?" / "–Vill du veta vad jag heter?"), even when both would fit on one line. A dash only counts as a new speaker after a sentence end, so "-20 degrees" is left alone; with `--max-lines 1` nothing changes. A sentence end is now preferred over a comma or a more even split ("Okay, dump the Kenny G's at half price." / "What else we got?" instead of breaking after "at"). On four 5-minute TV clips, 25 of 218 subtitles got a different line break; words and timing are unchanged.
- Subtitles are no longer cut where Whisper's segments end. Whisper often ends a segment mid-sentence, one word early ("Musso's looking for" / "you. Not a problem."), which made cues that stopped mid-sentence and many one-word cues. With word timestamps (the default), the words of neighbouring segments are now grouped together and cues end at pauses, sentence ends and the line limits. On a 5-minute sitcom clip, cues ending mid-sentence went from 27 to 4; over four 5-minute TV clips (English and Swedish), one- or two-word cues went from 40 to 15. Segments without word timing are handled as before.
- The code is now fully type annotated and checked with `mypy --strict` in CI. There is no change in behaviour.
- The command line code is split into smaller functions (parser, settings, output planning, model loading). There is no change in behaviour.
- `ctranslate2` (4.6 up to, not including, 5) and `numpy` (1.22 or newer) are now declared dependencies. The code imports them directly, so they no longer depend on faster-whisper pulling them in. Earlier ctranslate2 builds need an executable stack and fail to load on current Linux systems.
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
