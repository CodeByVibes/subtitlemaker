"""PySide6 itself must not leak references, or the app dies after a while.

PySide6 6.12.0 forgets to take a reference to `None` when a method returns
nothing. On Python 3.10 and 3.11 `None` is an ordinary object with a few
thousand references, so about five thousand such calls (a few thousand log
lines, say) drive the count to zero and the interpreter aborts with
"none_dealloc". Python 3.12 made `None` immortal, which hides the bug there.

If this test fails, the PySide6 in use has that bug: do not raise the version
cap in pyproject.toml to a release that fails it.
"""

import sys

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QPlainTextEdit  # noqa: E402

CALLS = 300


def drift(object_, call):
    before = sys.getrefcount(object_)

    for _ in range(CALLS):
        call()

    return sys.getrefcount(object_) - before


def test_methods_that_return_nothing_do_not_drain_the_references_to_none(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)

    # A leak shows as about -CALLS; ordinary bookkeeping moves the count by a few.
    assert drift(None, edit.clear) > -CALLS // 10
    assert drift(None, lambda: edit.setPlainText("x")) > -CALLS // 10
    assert drift(None, lambda: edit.appendPlainText("x")) > -CALLS // 10


def test_methods_that_return_a_bool_do_not_drain_the_references_to_it(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)

    assert drift(True, edit.isReadOnly) > -CALLS // 10
    assert drift(False, edit.isHidden) > -CALLS // 10
