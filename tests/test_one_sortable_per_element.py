"""גרירת קבוצה הפסיקה לעבוד ככל שהלוח נשאר פתוח.

Sortable hangs its listeners on the element and keeps only a reference to itself
there, so constructing a second one on the same element overwrites the reference
and leaves the first bound and listening. Most of the lists are rebuilt from
innerHTML — a new element each render, nothing to collide with — but the board
view is not: renderView empties #view and never replaces it, and #view is the
container the groups are dragged inside. Every re-render of a board added
another instance, and a board re-renders constantly (a cell edited, a filter,
a sort, a live update, a drag landing), so two instances raced to drag the same
group on one pointerdown, then three, then four.

Item drag was never affected: its tbody is thrown away and rebuilt each render.
That is why this presented as a fault in group dragging alone, and why reading
the group drag code found nothing wrong with it.

The harness runs the real sortableOn under node against a stand-in Sortable, and
checks that every list in the app is created through it.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "one_sortable_per_element.mjs"


def test_rendering_a_board_twice_leaves_one_sortable_not_two():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
