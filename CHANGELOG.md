# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- Subtitles now appear 0.15 s later than before (new `--start-offset`, and `start_offset` in the `[style]` section; 0 gives the old timing). Whisper's word times run early: on 17 episodes in English and Swedish (large-v3), cues started a median 0.35 s before the voice, and 0.29 s (turbo) and 0.22 s (small) on the same material. With the offset the median is 0.21, 0.15 and 0.08 s early, and the share of cues that start more than 0.15 s after the voice stays within 2 points on all three models (20% to 22% on large-v3). Cues built from whole segments, because a segment had no word timing, are moved the same way, so a file that mixes both keeps its order and gaps. The offset must be between -30 and 30 seconds. The setting is in the desktop app's style form too. Output is not byte-identical to 0.3.0 unless you pass `--start-offset 0`.

### Fixed
- A sentence that Whisper repeats with all its words squeezed into a fraction of a second is no longer shown as a flash of 0.1 s. Whisper large-v3 sometimes says a sentence again in its transcript (Letterkenny S01E01 at 5:40: one 25 word sentence came back three times in 0.4 s). A segment is now left out when it has at least 6 words, they are spoken faster than 20 per second, and at least 80% of its words repeat, in order, text from the previous 80 words. Squeezed words that say something new are kept, and so are normal repetitions and short phrases. On 23 transcripts of 17 real episodes (English and Swedish) only 8 segments qualified, and every one that could be checked against the human subtitles (six of them) was a duplicate. A repeat with one changed word is dropped too. Each run that drops something warns with the first three sentences (and the warning is in the app's result), so a wrong drop does not go unnoticed; the dropped words stay in Whisper's raw output.
- A file that was cut off (an interrupted download) no longer gives nonsense progress and speed. Its container can claim hours it does not have: a 20 minute file said 9 hours 45 minutes, so the progress bar stalled near 2% and the log reported "249.91x realtime" (really about 9x). The length of the audio that was actually decoded is now used when it differs from the container's by more than 10 seconds and 2%, with a warning that names both ("says it is 09:45:38 long, but its audio is 00:20:25. That is normal if the audio is shorter than the video; otherwise the file may be cut off or damaged."), and also when the container gives no duration at all. Normal files, where the two agree, are untouched.

## [0.3.0] - 2026-11-19

### Added
- A desktop app: `subtitlemaker-gui` (or `python -m subtitlemaker.gui`), installed with `pip install "subtitlemaker[gui]"`. It is optional: the command line never loads Qt, and without the extra the command explains what to install. It has three tabs.
  - **Queue:** add files and folders (dialogs or drop them), start, watch progress with speed and time left, cancel, reorder, remove, queue again, and choose where the subtitles go. Cancel then Start resumes; finished and failed files wait for "Queue again". The command line's guards apply (two files writing one output, an output overwriting its input, `--skip-existing`). One bad file does not stop the rest.
  - **Settings:** the options of the command line, with its help text as tooltips. It starts from your `config.toml`, remembers only what you changed in `~/.config/subtitlemaker/SubtitleMaker.conf`, and shows a mistake at the top as you make it.
  - **Log:** the command line's messages as they happen, warnings and errors coloured, "Show details" for `-v`.
  - **About** (the button in the corner of the tab bar, or F1): version, links, credits, and the details a bug report needs with a "Copy details" button. The home folder is written as `~` in them.
  - A **preview** of a finished file's subtitles, where the style can be changed and the subtitles are built again at once without running the model (a few milliseconds). The result is identical to running the command line again with those options: checked byte for byte on an English and a Swedish clip, in three styles each. Save replaces the file's subtitle files; "Use this style for new files" copies the style to the settings.
  - It works in a window about 500 pixels wide. Tested on Linux (Wayland) with PySide6 6.8 and 6.11 on Python 3.10 to 3.13; dropping from a real file manager is untested.
- `packaging/` has a desktop entry and an icon for application launchers, and a test keeps them in step with the app.
- Standalone apps (no Python needed), built by a new workflow for Linux (an AppImage and a `.tar.gz`), Windows (a `.zip`) and macOS (a `.dmg`, for Apple Silicon only: `onnxruntime`, which the voice-activity model needs, has no wheels for Intel Macs after version 1.23.2, which `pip install` still picks there) and attached to the GitHub Release. They are CPU only, because the CUDA libraries alone would add 1.3 GB, and they are not signed. Each build runs the app's own self-check, with a real transcription, before it is kept. The Linux app was built and run here (210 MB as a `.tar.gz`, 193 MB as an AppImage); the Windows and macOS ones have never been run by hand. See the README for what users will see.
- The desktop app shows a model download. The first use of a model used to look frozen for minutes, because a windowed app has no console for Hugging Face's progress bar. The queue screen now says "Downloading the small model (first use only): 231 of 462 MB (50%)" and the log says the model's size and that it happens once. Checked with an empty Hugging Face cache and the `tiny` model: 95 progress reports, then a finished transcription. The library's `JobRunner` has a matching `model_download` event.
- `subtitlemaker-gui --version`, and `subtitlemaker-gui --self-check` (with `--audio FILE --model NAME` for a real transcription and `--report FILE`): one line per thing the app needs (the libraries it imports, the voice-activity model, the icon plugin, the main window, a transcription) and whether it works. It is how a packaged app is checked, and it also works from a normal install.

### Changed
- The `gui` extra needs PySide6 6.8 or newer and older than 6.12. PySide6 6.12.0 leaks a reference to `None` on every call that returns nothing; on Python 3.10 and 3.11 that aborts the program after a few thousand calls, which a long log or a long session reaches. Python 3.12 and newer are not affected. A test (`tests/gui/test_pyside_health.py`) fails on a PySide6 with the bug.
- A packaged app never tries the GPU, even on a machine with an NVIDIA GPU. With the automatic settings it would have chosen `large-v3`, downloaded its 2.9 GB, and only then found that CUDA cannot start. It now uses the CPU and the `small` model, and the settings tab and the error messages say how to get GPU support (install with pip). Installs from PyPI are not affected.
- In a packaged app the About box and its "Copy details" text report the versions of faster-whisper and CTranslate2 (they were "unknown", because a packaged app has no package metadata).
- The work a run does for one file, building settings from plain values, and a background queue now live in importable modules (`pipeline`, `planning`, `settings`, `runner`) that the command line and the app share, instead of in the command line code. The command line behaves exactly as before: compared on real runs (three formats, a two minute clip, a batch with a corrupt file, translation, `--skip-existing`, every error path) the subtitle files, output, messages and exit codes were identical, except that when two mistakes are made at once a different one may be reported first. These modules are not yet a documented, stable API.
- CI also runs the desktop app's tests (without a display), checks that the command line installs and works without PySide6, and checks that the icon is in the wheel.

## [0.2.0] - 2026-11-08

### Added
- `--prompt TEXT` (and `initial_prompt` in the `[model]` section of the config file): text Whisper continues from. When a recording starts mid-sentence, Whisper can write minutes of text with no punctuation or capitals; a punctuated prompt fixes that. On three such 5-minute clips of a sitcom, punctuation went from 0–7% of words to 20–27%, the same as the rest of the episode. Off by default: on a Swedish programme with broadcast subtitles to compare against, prompts changed the word error rate by −1.4 to +6.4 points, with no prompt reliably better.
- `--hallucination-silence-threshold SEC` (and `hallucination_silence_threshold` in `[model]`): passes faster-whisper's option of the same name, which skips long silences where the text looks invented. Off by default. Against SVT's own subtitles for a Swedish programme (four 5-minute windows) a value of 2 never made the word error rate worse and lowered it from 31.7% to 27.8% in one window; on an English sitcom it changed some wording either way.
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

[Unreleased]: https://github.com/CodeByVibes/subtitlemaker/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/CodeByVibes/subtitlemaker/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/CodeByVibes/subtitlemaker/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/CodeByVibes/subtitlemaker/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/CodeByVibes/subtitlemaker/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/CodeByVibes/subtitlemaker/releases/tag/v0.1.0
