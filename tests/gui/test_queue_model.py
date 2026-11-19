"""`QueueModel`: the rules of the file list, without any widget."""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QModelIndex, Qt  # noqa: E402

from subtitlemaker.gui.queue_model import (  # noqa: E402
    COL_DURATION,
    COL_FILE,
    COL_PROGRESS,
    COL_STATUS,
    ITEM_ROLE,
    PROGRESS_ROLE,
    QueueModel,
    Status,
    format_duration,
)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def model(clock):
    return QueueModel(clock=clock)


def touch(folder: Path, *names: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []

    for name in names:
        path = folder / name
        path.write_bytes(b"")
        paths.append(path)

    return paths


def names(model):
    return [item.path.name for item in model.items()]


def cell(model, row, column, role=Qt.ItemDataRole.DisplayRole):
    return model.index(row, column).data(role)


# --- adding files -----------------------------------------------------------------


def test_files_are_added_in_the_order_given(model, tmp_path):
    a, b = touch(tmp_path, "a.mp3", "b.mp3")

    result = model.add_paths([b, a])

    assert names(model) == ["b.mp3", "a.mp3"]
    assert result.added == [b, a]
    assert result.duplicates == 0
    assert result.problems == []


def test_adding_announces_the_new_rows_once(model, tmp_path):
    inserted = []
    model.rowsInserted.connect(lambda parent, first, last: inserted.append((first, last)))

    model.add_paths(touch(tmp_path, "a.mp3"))
    model.add_paths(touch(tmp_path, "b.mp3", "c.mp3"))

    assert inserted == [(0, 0), (1, 2)]


def test_the_same_file_is_not_added_twice(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    (tmp_path / "sub").mkdir()

    model.add_paths([a])
    # the same file spelled two other ways: still one file, already in the list
    result = model.add_paths([tmp_path / "." / "a.mp3", tmp_path / "sub" / ".." / "a.mp3"])

    assert names(model) == ["a.mp3"]
    assert result.added == []
    assert result.duplicates == 1
    assert result.problems == []


def test_a_file_repeated_in_one_call_is_added_once(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")

    result = model.add_paths([a, a])

    assert names(model) == ["a.mp3"]
    assert result.added == [a]


def test_a_folder_adds_its_media_files_sorted(model, tmp_path):
    touch(tmp_path / "talks", "b.mp4", "a.mkv", "notes.txt", "cover.jpg", "._a.mkv")

    model.add_paths([tmp_path / "talks"])

    assert names(model) == ["a.mkv", "b.mp4"]  # no text, no image, no macOS metadata file


def test_sub_folders_are_only_scanned_when_asked(model, tmp_path):
    touch(tmp_path / "talks", "top.mp3")
    touch(tmp_path / "talks" / "deeper", "inner.mp3")

    model.add_paths([tmp_path / "talks"], recursive=False)
    assert names(model) == ["top.mp3"]

    model.add_paths([tmp_path / "talks"], recursive=True)
    assert names(model) == ["top.mp3", "inner.mp3"]


def test_something_that_does_not_exist_is_a_problem_not_an_error(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")

    result = model.add_paths([tmp_path / "missing.mp3", a])

    assert names(model) == ["a.mp3"]
    assert len(result.problems) == 1
    assert "does not exist" in result.problems[0]


def test_an_empty_folder_adds_nothing(model, tmp_path):
    (tmp_path / "empty").mkdir()

    result = model.add_paths([tmp_path / "empty"])

    assert result.added == [] and model.rowCount() == 0


# --- what the table shows -----------------------------------------------------------


def test_the_cells_show_name_duration_status_and_progress(model, tmp_path):
    (a,) = touch(tmp_path, "talk.mp3")
    model.add_paths([a])

    assert cell(model, 0, COL_FILE) == "talk.mp3"
    assert cell(model, 0, COL_FILE, Qt.ItemDataRole.ToolTipRole) == str(a)
    assert cell(model, 0, COL_DURATION) == ""  # not known yet
    assert cell(model, 0, COL_STATUS) == "Queued"
    assert cell(model, 0, COL_PROGRESS) == ""
    assert cell(model, 0, COL_PROGRESS, PROGRESS_ROLE) is None


def test_the_column_headers(model):
    headers = [
        model.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        for c in range(4)
    ]

    assert headers == ["File", "Duration", "Status", "Progress"]
    assert model.columnCount() == 4


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0:00"), (5, "0:05"), (59.9, "0:59"), (60, "1:00"), (123, "2:03"), (3723, "1:02:03")],
)
def test_durations_read_like_a_player_shows_them(seconds, text):
    assert format_duration(seconds) == text


def test_a_running_file_shows_its_percentage(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])
    model.mark_waiting(a, {"srt": tmp_path / "a.srt"})
    model.on_started(a)

    model.on_progress(a, 15.0, 60.0)

    assert cell(model, 0, COL_PROGRESS) == "25%"
    assert cell(model, 0, COL_PROGRESS, PROGRESS_ROLE) == pytest.approx(0.25)
    assert cell(model, 0, COL_DURATION) == "1:00"  # learned from the progress report


def test_progress_never_leaves_zero_to_one(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])
    model.on_started(a)

    model.on_progress(a, 75.0, 60.0)  # past the end

    assert cell(model, 0, COL_PROGRESS, PROGRESS_ROLE) == 1.0


def test_unknown_duration_gives_no_percentage(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])
    model.on_started(a)

    model.on_progress(a, 15.0, 0.0)

    assert cell(model, 0, COL_PROGRESS, PROGRESS_ROLE) is None
    assert cell(model, 0, COL_PROGRESS) == ""


def test_the_item_is_available_to_delegates(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])

    assert cell(model, 0, COL_FILE, ITEM_ROLE) is model.item(0)


def test_bad_indexes_give_no_data(model):
    assert model.data(QModelIndex()) is None
    assert model.index(5, 0).data() is None


# --- following the runner ------------------------------------------------------------


def test_a_file_goes_through_waiting_running_done(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])
    out = {"srt": tmp_path / "a.srt"}

    model.mark_waiting(a, out)
    assert model.item(0).status is Status.WAITING
    assert model.item(0).outputs == out

    model.on_started(a)
    assert model.item(0).status is Status.RUNNING

    model.on_finished(a)
    assert model.item(0).status is Status.DONE
    assert cell(model, 0, COL_PROGRESS) == "100%"


def test_a_failure_keeps_its_message_for_the_tooltip(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])

    model.on_failed(a, "failed to process a.mp3: Invalid data")

    assert cell(model, 0, COL_STATUS) == "Failed"
    assert "Invalid data" in cell(model, 0, COL_STATUS, Qt.ItemDataRole.ToolTipRole)


def test_warnings_mark_a_finished_file(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])

    model.on_finished(a, ["Whisper wrote almost no punctuation", "second warning"])

    assert cell(model, 0, COL_STATUS) == "Done (warning)"
    tip = cell(model, 0, COL_STATUS, Qt.ItemDataRole.ToolTipRole)
    assert "almost no punctuation" in tip and "second warning" in tip


def test_a_clean_finish_has_no_warning_mark(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])

    model.on_finished(a, [])

    assert cell(model, 0, COL_STATUS) == "Done"


def test_cancelled_and_skipped(model, tmp_path):
    a, b = touch(tmp_path, "a.mp3", "b.mp3")
    model.add_paths([a, b])

    model.on_cancelled(a)
    model.mark_skipped(b, {"srt": tmp_path / "b.srt"})

    assert [i.status for i in model.items()] == [Status.CANCELLED, Status.SKIPPED]


def test_events_for_files_not_in_the_list_are_ignored(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])
    stranger = tmp_path / "stranger.mp3"

    model.on_started(stranger)
    model.on_progress(stranger, 1.0, 2.0)
    model.on_finished(stranger)
    model.on_failed(stranger, "x")
    model.on_cancelled(stranger)
    model.mark_waiting(stranger, {})
    model.set_duration(stranger, 5.0)

    assert [i.status for i in model.items()] == [Status.QUEUED]


def test_progress_after_the_file_is_finished_is_ignored(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])
    model.on_started(a)
    model.on_finished(a)

    model.on_progress(a, 3.0, 60.0)

    assert model.item(0).position == 0.0


def test_a_known_duration_is_stored_and_zero_is_not(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])

    model.set_duration(a, 90.0)
    model.set_duration(a, 0.0)  # a failed probe must not erase it

    assert cell(model, 0, COL_DURATION) == "1:30"


def test_every_change_is_announced_to_views(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])
    changed = []
    model.dataChanged.connect(lambda top, bottom: changed.append((top.row(), bottom.column())))

    model.on_started(a)

    assert changed == [(0, 3)]  # the whole row


# --- speed and time left ---------------------------------------------------------------


def test_speed_and_eta_come_from_the_time_since_the_first_report(model, clock, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])
    model.on_started(a)

    clock.now = 100.0
    model.on_progress(a, 0.0, 60.0)  # transcription starts
    assert model.speed(a) is None and model.eta(a) is None  # nothing to measure yet

    clock.now = 110.0
    model.on_progress(a, 20.0, 60.0)

    assert model.speed(a) == pytest.approx(2.0)  # 20 s of media in 10 s
    assert model.eta(a) == pytest.approx(20.0)  # 40 s left at 2x


def test_eta_is_zero_when_everything_is_transcribed(model, clock, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])
    model.on_started(a)
    model.on_progress(a, 0.0, 60.0)
    clock.now = 110.0
    model.on_progress(a, 60.0, 60.0)

    assert model.eta(a) == 0.0


def test_speed_is_unknown_for_a_file_that_is_not_running(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])

    assert model.speed(a) is None
    assert model.eta(a) is None
    assert model.speed(tmp_path / "nope.mp3") is None


# --- removing, clearing, moving, retrying -------------------------------------------------


def test_files_can_be_removed(model, tmp_path):
    model.add_paths(touch(tmp_path, "a.mp3", "b.mp3", "c.mp3", "d.mp3"))

    assert model.remove_rows([0, 2]) == 2

    assert names(model) == ["b.mp3", "d.mp3"]


def test_removing_announces_each_row_and_survives_duplicates_and_bad_rows(model, tmp_path):
    model.add_paths(touch(tmp_path, "a.mp3", "b.mp3"))
    removed = []
    model.rowsRemoved.connect(lambda parent, first, last: removed.append(first))

    assert model.remove_rows([1, 1, 99, -1]) == 1

    assert names(model) == ["a.mp3"]
    assert removed == [1]


@pytest.mark.parametrize("status", [Status.WAITING, Status.RUNNING])
def test_a_file_the_runner_has_cannot_be_removed(model, tmp_path, status):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])
    model._items[0].status = status

    assert model.remove_rows([0]) == 0
    assert model.clear() == 0

    assert names(model) == ["a.mp3"]


def test_clear_removes_everything_except_what_is_running(model, tmp_path):
    a, b, c = touch(tmp_path, "a.mp3", "b.mp3", "c.mp3")
    model.add_paths([a, b, c])
    model.on_started(b)

    assert model.clear() == 2

    assert names(model) == ["b.mp3"]


def test_a_removed_file_can_be_added_again(model, tmp_path):
    (a,) = touch(tmp_path, "a.mp3")
    model.add_paths([a])
    model.remove_rows([0])

    assert model.add_paths([a]).added == [a]


def test_files_move_up_and_down(model, tmp_path):
    model.add_paths(touch(tmp_path, "a.mp3", "b.mp3", "c.mp3"))

    assert model.move(2, -1) is True
    assert names(model) == ["a.mp3", "c.mp3", "b.mp3"]

    assert model.move(0, +1) is True
    assert names(model) == ["c.mp3", "a.mp3", "b.mp3"]


def test_files_cannot_move_past_the_ends(model, tmp_path):
    model.add_paths(touch(tmp_path, "a.mp3", "b.mp3"))

    assert model.move(0, -1) is False
    assert model.move(1, +1) is False
    assert model.move(5, -1) is False
    assert names(model) == ["a.mp3", "b.mp3"]


def test_a_file_the_runner_has_cannot_move_and_nothing_swaps_with_it(model, tmp_path):
    a, b, c = touch(tmp_path, "a.mp3", "b.mp3", "c.mp3")
    model.add_paths([a, b, c])
    model.mark_waiting(b, {})

    assert model.move(1, -1) is False  # it is the locked one
    assert model.move(0, +1) is False  # its neighbour is locked
    assert names(model) == ["a.mp3", "b.mp3", "c.mp3"]


def test_the_cells_follow_a_moved_file(model, tmp_path):
    a, b = touch(tmp_path, "a.mp3", "b.mp3")
    model.add_paths([a, b])
    model.on_failed(b, "boom")

    model.move(1, -1)

    assert cell(model, 0, COL_FILE) == "b.mp3"
    assert cell(model, 0, COL_STATUS) == "Failed"
    assert model.row_of(b) == 0


def test_finished_files_can_be_queued_again(model, tmp_path):
    a, b, c, d = touch(tmp_path, "a.mp3", "b.mp3", "c.mp3", "d.mp3")
    model.add_paths([a, b, c, d])
    model.on_finished(a)
    model.on_failed(b, "boom")
    model.on_cancelled(c)
    model.mark_waiting(d, {})

    assert model.requeue(range(4)) == 3  # the waiting one belongs to the runner

    assert [i.status for i in model.items()] == [
        Status.QUEUED,
        Status.QUEUED,
        Status.QUEUED,
        Status.WAITING,
    ]
    assert model.item(1).message == ""


def test_count_by_status(model, tmp_path):
    a, b, c = touch(tmp_path, "a.mp3", "b.mp3", "c.mp3")
    model.add_paths([a, b, c])
    model.on_started(a)
    model.mark_waiting(b, {})

    assert model.count() == 3
    assert model.count(Status.RUNNING) == 1
    assert model.count(Status.RUNNING, Status.WAITING) == 2
    assert model.count(Status.DONE) == 0
