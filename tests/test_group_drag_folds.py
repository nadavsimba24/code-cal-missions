"""Reordering groups by dragging, on a board that is open.

Dragging a group used to mean dragging its whole table: the group being moved
is as tall as its rows, the groups it has to travel past are as tall as theirs,
and the drop never comes within reach. It worked when the groups happened to be
folded, which is the same as saying it worked by accident.

So the board folds for the length of the drag — the groups become the short
list of headers that is actually being reordered — and unfolds into exactly
what it was when the drag is over, including the groups the user had folded
themselves. Picking a group up and putting it down must not cost anyone the
rows they had open.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "group_drag_folds.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_board_folds_for_the_drag_and_comes_back():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_there_is_one_place_that_folds_a_group():
    """The caret, the drag and the restore all fold groups. Three copies of
    "class, table, battery, state" is three chances for one of them to forget
    the progress bar and leave it floating under a folded group."""
    assert SRC.count("function foldGroup(head,shut)") == 1
    body = SRC[SRC.index("function foldGroup(head,shut)"):]
    body = body[:body.index("\n}") + 2]
    for part in ("classList.toggle('collapsed'", "nextElementSibling",
                 ".grp-batt", "setGroupCollapsed("):
        assert part in body, f"foldGroup no longer handles {part}"


def test_the_drag_is_still_only_offered_from_the_handle():
    """Folding on choose means a press on the handle changes the board before
    any movement. That is tolerable because the handle is the grip and the
    name — neither of which does anything else on a press — and because the
    board comes back on unchoose. If the handle ever widens, this stops being
    true."""
    assert "handle:'.g-handle'" in SRC
    assert 'class="g-name g-handle"' in SRC
