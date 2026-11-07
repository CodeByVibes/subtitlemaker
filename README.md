# SubtitleMaker

[![CI](https://github.com/CodeByVibes/subtitlemaker/actions/workflows/ci.yml/badge.svg)](https://github.com/CodeByVibes/subtitlemaker/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Generate subtitles from audio and video files with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
It runs locally, on a GPU if you have one and on the CPU if you don't.

```console
$ subtitlemaker interview.mkv
$ ls
interview.mkv  interview.srt
```

- **SRT, WebVTT and plain text** output, any combination in one run.
- **Subtitles that follow the speech.** Cues start at the first word and end at the last, using word timestamps, and long sentences are split at sentence ends where possible.
- **Readable by default:** at most two lines of 42 characters, 20 characters per second, 1 to 7 seconds on screen. All of it is configurable.
- **Batch mode:** pass many files or whole folders; the model is loaded once and one bad file doesn't stop the rest.
- **GPU or CPU.** `--device auto` uses an NVIDIA GPU when there is one and falls back to the CPU when there isn't.
- **Mixed-language audio** (`-l en,sv`), and optional translation to English (`-t translate`).

## Install

You need Python 3.10 to 3.13. FFmpeg is **not** required.

SubtitleMaker is a command line tool, so [pipx](https://pipx.pypa.io/) or [uv](https://docs.astral.sh/uv/) is the easiest way to install it:

```console
# CPU only
pipx install subtitlemaker

# NVIDIA GPU (also installs the CUDA 12 libraries, see below)
pipx install "subtitlemaker[cuda]"
```

With uv: `uv tool install subtitlemaker` or `uv tool install "subtitlemaker[cuda]"`. Plain `pip install` works too, ideally inside a virtual environment.

> **Platforms:** developed and tested on Linux. It should work on macOS and Windows on the CPU, but that has not been tested yet. GPU support is only set up for Linux.

### The first run downloads a model

Whisper models are downloaded from Hugging Face the first time you use them and cached afterwards (`~/.cache/huggingface`, or wherever `HF_HOME` points). Sizes of the model files:

| `--model`    | Download | Notes                                          |
| ------------ | -------- | ---------------------------------------------- |
| `tiny`       | 73 MB    | Fast, rough. Good for trying things out.       |
| `small`      | 462 MB   | **Default on CPU.**                            |
| `turbo`      | 1.6 GB   | Close to `large-v3` quality, much faster.      |
| `large-v3`   | 2.9 GB   | **Default on GPU.** Most accurate.             |

`base`, `medium`, the `.en` variants, `distil-*` models, any Hugging Face repo id such as `user/model`, and local paths to converted models also work.

## Usage

```console
# Subtitles next to the file, in the spoken language
subtitlemaker talk.mp4

# Several formats at once: talk.srt, talk.vtt and talk.txt
subtitlemaker talk.mp4 -f srt,vtt,txt

# English subtitles for foreign-language audio
subtitlemaker film.mkv -t translate

# Tell it the language instead of detecting it
subtitlemaker film.mkv -l sv

# A whole folder (add -r for sub folders), skipping files that are already done
subtitlemaker ~/Videos --skip-existing -r

# Put all the results in one place
subtitlemaker ~/Videos/*.mp4 -d ~/subtitles -f srt,vtt

# Smaller and faster, CPU only
subtitlemaker talk.mp4 --device cpu --model tiny
```

Run `subtitlemaker --help` for every option.

### Output

| Format | Contents                                                                         |
| ------ | -------------------------------------------------------------------------------- |
| `srt`  | SubRip, the most widely supported. This is the default.                          |
| `vtt`  | WebVTT, for web players. Markup characters in the text are escaped.              |
| `txt`  | The text only, one subtitle per line, no timing.                                 |

Files are written next to each input and named after it (`talk.mp4` becomes `talk.srt`). Existing files are overwritten unless you pass `--skip-existing`.

- `-o FILE` names the output for a single input. With several formats it is a base name and the extension is replaced for each one.
- `-d DIR` writes all outputs into one folder (created if needed). Two inputs that would write the same file are refused before anything runs.

The exit code is `0` when everything succeeded, `1` if any file failed (the others are still processed), and `2` for invalid options.

### Languages

By default Whisper detects the language from the start of each file. If it guesses wrong, or the start is music, name the language with `-l`.

For audio that switches language, list the languages (`-l en,sv`) or add `-m`. The language is then re-detected for every segment. Be aware that `-t translate` turns every segment into English.

### Subtitle style

| Option              | Default | Meaning                                              |
| ------------------- | ------- | ---------------------------------------------------- |
| `--max-line-length` | 42      | Maximum characters per line.                         |
| `--max-lines`       | 2       | Lines per subtitle, 1 or 2.                          |
| `--max-cps`         | 20      | Reading speed: characters per second.                |
| `--min-duration`    | 1.0     | Shortest time a subtitle stays on screen (seconds).  |
| `--max-duration`    | 7.0     | Longest time a subtitle stays on screen (seconds).   |
| `--min-gap`         | 0.05    | Smallest gap between two subtitles (seconds).        |

Timing follows the speech. A subtitle appears when its first word is spoken. If it would be too short or too quick to read, it is held longer, but only into free time: it never delays or overlaps the next subtitle. If two lines are spoken too close together, the first one is allowed to be shorter than `--min-duration`.

### Config file

Options you always use can go in `~/.config/subtitlemaker/config.toml` (or `$XDG_CONFIG_HOME/subtitlemaker/config.toml`), or in a file given with `--config`. Command line options override the file, and the file overrides the defaults.

```toml
[style]
max_line_length = 38
max_lines = 2
max_cps = 17
min_duration = 1.0
max_duration = 6.0
min_gap = 0.05

[model]
name = "turbo"            # auto, a size, a Hugging Face repo id or a path
device = "auto"           # auto, cuda or cpu
compute_type = "auto"     # auto, float16, int8_float16, int8, float32, ...
word_timestamps = true
vad_filter = true
condition_on_previous_text = true
```

Unknown keys and wrong types are reported with the file name, so typos don't pass silently.

## GPU and CPU

`--device auto` (the default) picks the GPU when CTranslate2 can see one and warns and uses the CPU otherwise.

| Where | Default model | Precision | Notes                                               |
| ----- | ------------- | --------- | --------------------------------------------------- |
| GPU   | `large-v3`    | `float16` | Needs an NVIDIA GPU, a current driver and CUDA 12 libraries. |
| CPU   | `small`       | `int8`    | Works everywhere, much slower than a GPU.           |

For a rough idea, on one machine (RTX 4070 Laptop GPU, 24 CPU cores) a two minute clip took about 7 seconds with `large-v3` on the GPU and about 9 seconds with `small` on the CPU. Your results will differ.

### CUDA libraries

CTranslate2 needs the CUDA 12 versions of cuBLAS and cuDNN 9. Install SubtitleMaker with the `cuda` extra and they come from PyPI (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) and are loaded automatically, so a different system-wide CUDA version doesn't matter. These packages are licensed by NVIDIA, not under this project's license, and they are large.

If the GPU can't be used, `--device auto` falls back to the CPU and tells you why. With an explicit `--device cuda` it stops with an error that says what is missing.

## How it works

1. faster-whisper transcribes the audio with word timestamps (voice activity detection is on, so stretches without speech are skipped).
2. Words are grouped into subtitles that fit the line limits, preferably breaking at the end of a sentence.
3. Timing is adjusted for readability without moving speech, as described above.
4. The result is written in each requested format.

## Limitations

- At most two lines per subtitle.
- Lines are wrapped at spaces, so languages written without spaces (Chinese, Japanese, Thai) are not wrapped well. This is untested.
- Speakers are not identified, and no sound descriptions like `[music]` are added.
- A long pause in the middle of a sentence does not split the subtitle yet.

## Contributing

Bug reports and pull requests are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE). SubtitleMaker builds on [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT), [CTranslate2](https://github.com/OpenNMT/CTranslate2) (MIT) and OpenAI's [Whisper](https://github.com/openai/whisper) models (MIT).
