"""The app build workflow keeps the properties that matter (checked as text: it never runs here)."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "build-apps.yml"

pytestmark = pytest.mark.skipif(not WORKFLOW.is_file(), reason="not running from a source checkout")


@pytest.fixture(scope="module")
def text():
    return WORKFLOW.read_text(encoding="utf-8")


def job(text: str, name: str) -> str:
    """The text of one job (from its heading to the next job)."""

    match = re.search(rf"^  {name}:\n(.*?)(?=^  \w[\w-]*:\n|\Z)", text, re.M | re.S)

    assert match, f"no job {name}"

    return match.group(1)


# --- what goes into the apps ------------------------------------------------------------------


def test_the_apps_are_built_without_cuda_and_without_the_dev_tools(text):
    syncs = [line for line in text.splitlines() if "uv sync" in line]

    assert syncs, "no uv sync"
    for line in syncs:
        assert "--extra cuda" not in line and "cuda" not in line  # 1.3 GB nobody asked for
        assert "--no-dev" in line  # and nothing but what the app needs
        assert "--locked" in line  # exactly the versions in uv.lock
        assert "--no-editable" in line  # installed as a user's copy would be


def test_every_build_checks_the_built_app_before_it_is_kept(text):
    block = job(text, "build")

    assert block.count("packaging/build.py") == 2  # one step for Linux, one for the others
    assert block.count("--self-check-audio tests/fixtures/jfk.flac") == 2  # and both check


def test_the_linux_build_uses_the_pinned_tools(text):
    block = job(text, "build")

    assert "--appimagetool" in block and "--appimage-runtime" in block
    assert block.count("sha256sum -c -") == 2  # both downloads are checked

    for digest in re.findall(r'echo "([0-9a-f]+)  (?:appimagetool|runtime-x86_64)"', block):
        assert len(digest) == 64


def test_the_tag_must_match_the_version_before_anything_is_built(text):
    block = job(text, "build")

    assert "github.ref_type == 'tag'" in block
    assert "src/subtitlemaker/__init__.py" in block and "GITHUB_REF_NAME" in block
    assert block.index("must match the package version") < block.index("uv sync")


# --- who may write ----------------------------------------------------------------------------


def test_only_the_release_job_can_write_to_the_repository(text):
    assert re.search(r"^permissions:\n  contents: read\n", text, re.M)
    assert text.count("contents: write") == 1
    assert "contents: write" in job(text, "release")
    assert "contents: write" not in job(text, "build")


def test_attaching_to_a_release_waits_for_approval_on_a_tag_only(text):
    release = job(text, "release")

    assert "needs: build" in release
    assert "if: github.ref_type == 'tag'" in release
    assert re.search(r"environment:\n\s+name: github-release", release)


def test_nothing_is_published_by_a_manual_run_or_a_pull_request(text):
    assert "gh release" not in job(text, "build")
    assert "gh release" in job(text, "release")
    assert "pull_request:" in text  # builds are checked when the packaging changes ...
    assert "if: github.ref_type == 'tag'" in job(text, "release")  # ... but only a tag releases


def test_the_checkout_does_not_keep_credentials(text):
    assert text.count("persist-credentials: false") == 1  # the build job's checkout
    assert "actions/checkout@" in text and "uses: actions/checkout" in job(text, "build")
    assert "actions/checkout" not in job(text, "release")  # the release job needs no source


# --- the matrix and the build script agree ----------------------------------------------------


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location(
        "subtitlemaker_build_wf", ROOT / "packaging" / "build.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["subtitlemaker_build_wf"] = module
    spec.loader.exec_module(module)

    return module


EXPECTED = {
    "ubuntu-22.04": ("Linux", "x86_64", "linux-x86_64"),
    "windows-latest": ("Windows", "AMD64", "windows-x64"),
    "macos-latest": ("Darwin", "arm64", "macos-arm64"),
}


def test_each_matrix_entry_makes_the_files_the_artifact_pattern_collects(text, build):
    entries = re.findall(r"os: ([\w.-]+), tag: ([\w-]+)", text)

    assert sorted(os for os, tag in entries) == sorted(EXPECTED)

    for os_name, tag in entries:
        system, machine, expected = EXPECTED[os_name]

        assert tag == expected == build.platform_tag(system, machine)
        assert build.artifact_name("0.3.0", tag, ".x").startswith(
            "SubtitleMaker-"
        )  # `SubtitleMaker-*`

    assert "path: apps/SubtitleMaker-*" in text  # and not the per-system SHA256SUMS


def test_the_runner_for_linux_is_the_oldest_available_for_the_widest_glibc(text):
    assert "os: ubuntu-22.04" in text and "ubuntu-latest" not in job(text, "build")
