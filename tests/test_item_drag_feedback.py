"""A drag says a move happened only when one did — and can reach the group.

Two reports, one gesture. Dropping a row back where it was picked up from sent
a move to the server, refetched the board and announced "הפריט הועבר": a
success message for nothing. And the reason a drag so often ended nowhere is
that moving an item to another group meant holding the row down while scrolling
the board to reach it. So for the length of the gesture the board shrinks to its
group names, every group's "+ הוסף פריט" line staying as the strip to drop on,
and whichever group the pointer is over opens so a position inside it is still
a thing that can be chosen. None of it is remembered once the drag ends.

The harness runs the real itemSpot/sameSpot/itemDragChrome/itemDragOpen under
node over a stub DOM, and reads the CSS and the wiring out of index.html; it
names the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "item_drag_feedback.mjs"


def test_a_drag_that_moved_nothing_announces_nothing():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
