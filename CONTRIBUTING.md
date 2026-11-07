# Contributing

Thanks for wanting to help. Bug reports, ideas and pull requests are all welcome.

## Reporting a problem

Please include:

- what you ran (the full command) and what you expected,
- the output, ideally with `-v` for debug messages,
- your OS, Python version and `subtitlemaker --version`,
- whether it was on the GPU or the CPU.

If a particular file triggers the problem and it is short and shareable, attach it. Otherwise a description of it (length, languages, container) helps.

## Setting up

You need Python 3.10 or newer and [uv](https://docs.astral.sh/uv/).

```console
git clone https://github.com/CodeByVibes/subtitlemaker.git
cd subtitlemaker
uv sync                 # add --extra cuda for NVIDIA GPU support
uv run subtitlemaker --help
```

## Checks

```console
uv run ruff check src tests     # lint
uv run pytest                   # unit, snapshot and pipeline tests: fast, no GPU or model needed
uv run pytest -m integration    # runs the real "tiny" model on a short clip (downloads 73 MB once)
```

CI runs the lint and the fast tests on Python 3.10 to 3.13, and the integration tests once. Please make sure these pass before opening a pull request.

The code style is plain and spacious. Run `ruff check`, but do not run `ruff format` over `src/`, it would rewrite the whole code base.

## How the code is organised

| Module             | Responsibility                                                    |
| ------------------ | ----------------------------------------------------------------- |
| `cli.py`           | Arguments, batch handling, the per-file steps.                    |
| `config.py`        | `SubtitleStyle` and `ModelConfig`, config file loading, validation. |
| `transcribe.py`    | Choosing and loading the model, GPU/CPU fallback, languages.      |
| `_cuda.py`         | Loading the pip-installed CUDA libraries.                         |
| `segmenter.py`     | Whisper segments to subtitle cues. **Pure logic**: no printing, files or model. |
| `formats/`         | Output writers (`srt`, `vtt`, `txt`) and the registry.            |
| `media.py`         | Reading durations, finding media files in folders.                |
| `progress.py`, `log.py` | The progress bar and logging.                                |

Keep `segmenter.py` free of I/O. That is what makes the subtitle behaviour testable without a model.

### Adding an output format

1. Write `formats/yourformat.py` with a `write_yourformat(cues, path)` function. A cue is a dict with `start` and `end` (seconds) and `text` (lines separated by `\n`).
2. Register it in `formats/__init__.py`.
3. Add tests next to the ones in `tests/test_output_formats.py`. If the format has an external specification, check a generated file with an independent tool (we use `ffmpeg` for SRT and VTT).

### Changing subtitle behaviour

Timing and splitting changes show up in the snapshot tests. If a change is intended, regenerate the stored files, read the diff, and explain it in the pull request:

```console
UPDATE_SNAPSHOTS=1 uv run pytest tests/test_snapshot.py
git diff tests/fixtures
```

## Tests

- Test behaviour, not implementation. The existing tests build "segments" by hand (`tests/conftest.py`) and run them through the real code.
- `tests/conftest.py` has a fake Whisper model (`fake_model`) and a `run(...)` helper so the whole command line can be tested without a GPU.
- A test that has never failed is a test you don't know works. When you fix a bug, write the test first and watch it fail.

## Commits and pull requests

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `build:`, `chore:`. Keep each commit to one logical change, and add a line to `CHANGELOG.md` under "Unreleased" for anything a user would notice.

## Releasing (maintainers)

1. Move the "Unreleased" entries in `CHANGELOG.md` under a new version heading with the date.
2. Set the version in `src/subtitlemaker/__init__.py` (it is the single source for the package version).
3. Commit, then tag: `git tag v0.2.0 && git push origin main v0.2.0`.
4. The `Publish` workflow builds the package, checks the tag matches the version, runs the tests and uploads to PyPI with trusted publishing. No tokens are stored anywhere.
