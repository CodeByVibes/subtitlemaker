"""The desktop app must not get in the way of the command line.

These run without Qt being used, whether or not PySide6 is installed.
"""

import subprocess
import sys


def _python(code: str):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


def test_the_library_and_cli_never_import_qt():
    result = _python(
        "import sys\n"
        "import subtitlemaker, subtitlemaker.cli, subtitlemaker.runner, subtitlemaker.gui\n"
        "print('QT', sorted(m for m in sys.modules if m.startswith(('PySide', 'shiboken'))))\n"
    )

    assert "QT []" in result.stdout, result.stdout + result.stderr


def test_without_pyside6_the_app_explains_what_to_install():
    # `None` in sys.modules makes `import PySide6` fail, as if it were not installed.
    result = _python(
        "import sys\n"
        "sys.modules['PySide6'] = None\n"
        "from subtitlemaker.gui import main\n"
        "sys.exit(main())\n"
    )

    assert result.returncode == 1
    assert "pip install 'subtitlemaker[gui]'" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_running_the_module_without_pyside6_gives_the_same_message():
    result = _python(
        "import runpy, sys\n"
        "sys.modules['PySide6'] = None\n"
        "runpy.run_module('subtitlemaker.gui', run_name='__main__')\n"
    )

    assert result.returncode == 1
    assert "pip install 'subtitlemaker[gui]'" in result.stderr
    assert "Traceback" not in result.stderr


def test_version_works_without_pyside6():
    result = _python(
        "import sys\n"
        "sys.modules['PySide6'] = None\n"
        "from subtitlemaker.gui import main\n"
        "sys.exit(main(['--version']))\n"
    )

    import subtitlemaker

    assert result.returncode == 0
    assert result.stdout.strip() == f"subtitlemaker-gui {subtitlemaker.__version__}"


def test_the_self_check_without_pyside6_says_what_is_missing():
    result = _python(
        "import sys\n"
        "sys.modules['PySide6'] = None\n"
        "from subtitlemaker.gui import main\n"
        "sys.exit(main(['--self-check']))\n"
    )

    assert result.returncode == 1
    assert "pip install 'subtitlemaker[gui]'" in result.stderr
    assert "Traceback" not in result.stderr


def test_the_help_lists_the_packaging_options():
    result = _python(
        "from subtitlemaker.gui import main\n"
        "main(['--help'])\n"
    )

    assert result.returncode == 0
    for option in ("--version", "--self-check", "--audio", "--model", "--report"):
        assert option in result.stdout, option
