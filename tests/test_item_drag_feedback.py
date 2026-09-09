"""A drag reorders a group, and says a move happened only when one did.

Two rules, one gesture. Dropping a row back where it was picked up from sent a
move to the server, refetched the board and announced "הפריט הועבר": a success
message for nothing. And a drag used to be able to carry an item into another
group — with the whole board folding up to its group names to make the other
group reachable. Which group an item belongs to is a decision about the work,
taken deliberately in the item's menu or the bulk bar, so a drag now stays
inside the group it started in: each group's tbody is a Sortable of its own,
the board is never folded, and the item's status is left alone.

The message rule covers all three things a board lets you drag — an item, a
sub-item and a whole group — because it is the same false success in each.

The harness runs the real itemSpot/sameSpot under node over a stub DOM, and
reads the CSS and the wiring out of index.html; it names the failing case.
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
