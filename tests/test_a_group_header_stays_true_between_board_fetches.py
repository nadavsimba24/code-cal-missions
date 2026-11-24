"""The number over a group goes on being right after the board is edited.

The board counts each of its groups when it is opened — `group_counts`, one
figure per group, counted in the database through this reader's own permission
filter — and past the client threshold that figure is the only thing on the
screen that knows how big a group is: the rows come down a page at a time, so
anything recounted from them is a count of what has been scrolled past.

The board is then deliberately not fetched again after every change. An item
created, deleted, duplicated or moved between groups is applied to the rows in
hand and redrawn in place, because a refetch of a board this size is exactly
the flash that the paging exists to avoid. Which leaves the figure that arrived
wrong by one, and the redraw of the header with no honest number to use.

Both failures were real and they pointed opposite ways. The redraw after a
deletion recomputed the header from the rows it could see, so a group holding
942 items printed "2" the moment anything was deleted from it. And nothing
corrected the board's own figure, so a header that did read it kept saying 942
after the row was gone. The fix is one correction (`bumpGroupCount`) applied by
each path that changes the board locally, and a redraw that reads the corrected
figure instead of counting rows (`refreshGroupStats`).

The harness runs those functions out of index.html against a board in each
state — paged, fully loaded, and from a backend that sends no counts at all —
and reads the number the header is left showing. There is no DOM: the two nodes
the redraw writes to are stubs, which is all it touches.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "group_count_local_edits.mjs"


def test_the_group_header_survives_an_edit_that_does_not_refetch_the_board():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
