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
uv run subtitlemaker-gui    # the desktop app
```

`uv sync` also installs PySide6 and pytest-qt (they are in the dev group), so the desktop app's tests run. A plain `uv sync` removes the CUDA libraries from an environment that has them: if you use the GPU, always add `--extra cuda`.

## Checks

```console
uv run ruff check src tests     # lint
uv run mypy                     # type check (strict)
uv run pytest                   # unit, snapshot, pipeline and desktop app tests: fast, no GPU or model needed
uv run pytest -m integration    # runs the real "tiny" model on a short clip (downloads 73 MB once)
```

CI runs the lint, the type check and the fast tests on Python 3.10 to 3.13, a run with the lowest supported dependencies, a check that the command line installs and works without PySide6, and the integration tests once. Please make sure these pass before opening a pull request.

The desktop app's tests (`tests/gui/`) run without a display: they set `QT_QPA_PLATFORM=offscreen` themselves, even if your session exports another value, so no windows appear. They are skipped when PySide6 is not installed. On Linux, Qt needs a few system libraries to start even offscreen (CI installs `libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3`).

The code style is plain and spacious. The code is fully type annotated and checked with `mypy --strict`; keep new code annotated. Run `ruff check`, but do not run `ruff format` over `src/`, it would rewrite the whole code base.

## How the code is organised

| Module             | Responsibility                                                    |
| ------------------ | ----------------------------------------------------------------- |
| `cli.py`           | Arguments, and the batch loop of the command line.                |
| `pipeline.py`      | `process_file`: transcribe one file and write its subtitles, with progress and cancel. Keeps the transcript so `FileResult.rebuild` can build the subtitles again. |
| `planning.py`      | Which files to process and where each output goes (and the guards). |
| `settings.py`      | `resolve_settings`: defaults, config file and the user's choices from plain values, shared by the command line and the app. |
| `runner.py`        | `JobRunner`: a background queue that keeps one model loaded, with cancel. No Qt. |
| `config.py`        | `SubtitleStyle` and `ModelConfig`, config file loading, validation. |
| `transcribe.py`    | Choosing and loading the model, GPU/CPU fallback, languages.      |
| `_cuda.py`         | Loading the pip-installed CUDA libraries.                         |
| `segmenter.py`     | Whisper segments to subtitle cues. **Pure logic**: no printing, files or model. |
| `formats/`         | Output writers (`srt`, `vtt`, `txt`) and the registry.            |
| `media.py`         | Reading durations, finding media files in folders.                |
| `progress.py`, `log.py` | The progress bar and logging.                                |
| `gui/`             | The desktop app (PySide6, Qt Widgets): the queue, settings, log and preview screens, and `bridge.py`, which turns the runner's events into Qt signals. |

The library modules never import Qt, and neither does `gui/__init__.py`: the command line must work without PySide6, and `subtitlemaker-gui` has to be able to say what is missing. `gui/settings_form.py` is deliberately free of Qt too, so its rules (what the form holds, what is saved) are tested without a window.

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
- A test that has never failed is a test you don't know works. When you fix a bug, write the test first and watch it fail. Breaking the code on purpose and checking that a test fails is a good habit for anything new.
- In the desktop app's tests, make windows with the `make_window` fixture (`tests/gui/conftest.py`). It holds on to them and stops their worker threads, which pytest-qt does not do for you (it keeps only weak references and does not deliver close events). Dialogs that would block are replaced by recorded stand-ins.
- PySide6 is pinned below 6.12 because 6.12.0 leaks a reference to `None` on every call that returns nothing, which aborts Python 3.10 and 3.11 after a few thousand calls. `tests/gui/test_pyside_health.py` checks for it; run it against a newer PySide6 before raising the cap.
- `uv run --resolution lowest-direct` (the dependency floor check) rewrites `uv.lock`. Restore it afterwards (`git checkout -- uv.lock`) unless you also changed dependencies.

## Commits and pull requests

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `build:`, `chore:`. Keep each commit to one logical change, and add a line to `CHANGELOG.md` under "Unreleased" for anything a user would notice.

## Building the standalone apps

The apps are made with PyInstaller by `packaging/build.py`. The release workflow (`.github/workflows/build-apps.yml`) does it for Linux, Windows and macOS; you can also build the one for your own system:

```console
# An environment of its own: the gui extra and the build group, no dev tools, and NOT the cuda extra.
export UV_PROJECT_ENVIRONMENT=$HOME/.local/share/venvs/subtitlemaker-build
uv sync --locked --group build --extra gui --no-dev --no-editable
uv run --no-sync python packaging/build.py --self-check-audio tests/fixtures/jfk.flac
```

The result is in `/tmp/subtitlemaker-out` (`--out` changes it) with a `SHA256SUMS` file. The build environment must not have the `cuda` extra: the app is CPU only, and the CUDA libraries would add 1.3 GB (`transcribe.cuda_available()` also refuses the GPU in a packaged app, so a bundle that did contain them would not use them). `--self-check-audio` runs the built app's own `--self-check`, including a real transcription of the clip, and stops the build if anything fails. On Linux, `appimagetool` on the `PATH` (or `--appimagetool PATH`) also makes an AppImage.

- A bundle built on a new Linux needs a glibc that new: the downloadable one is built on the oldest Ubuntu GitHub offers. A local build proves the mechanics, not portability.
- `appimagetool` downloads its runtime from the internet unless you give it one (`--appimage-runtime FILE`). CI does, pinned by checksum.
- Windows and macOS can only be built on those systems, so the CI run is the only test of those two. The parts that do not depend on the system (names, icons, archives, checksums) are tested in `tests/test_build_script.py`.
- If a feature uses a file that is not Python (a data file, a Qt plugin), a bundle may not contain it. Add it to `packaging/subtitlemaker.spec` and a check for it to `subtitlemaker/gui/selfcheck.py`: that is how the SVG icon plugin and the voice-activity model are covered.

### Before the first release that includes apps (maintainers, once)

The `Build apps` workflow attaches the files to the GitHub Release after approval of an environment called `github-release`. In the repository settings, under *Environments*, create `github-release` and add yourself as a required reviewer **before** pushing the tag. A workflow that names an environment that does not exist creates it with no protection, and the apps would be attached without anyone approving them.

## Releasing (maintainers)

1. Move the "Unreleased" entries in `CHANGELOG.md` under a new version heading with the date.
2. Set the version in `src/subtitlemaker/__init__.py` (it is the single source for the package version).
3. Commit, then tag: `git tag v0.2.0 && git push origin main v0.2.0`.
4. The `Publish` workflow builds the package, checks the tag matches the version, runs the tests and uploads to PyPI with trusted publishing. No tokens are stored anywhere.
5. The `Build apps` workflow starts on the same tag. It builds and self-checks the apps for all systems, then waits for you to approve the `github-release` environment. After approval it attaches the apps and a `SHA256SUMS` file to the release, and makes a **draft** release if there is none yet. So publish the draft (edit it and add the notes) instead of running `gh release create`, or create the release first and the apps are added to it.
