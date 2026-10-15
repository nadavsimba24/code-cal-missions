"""ריצוד על כל הלוח אחרי כל שינוי סטטוס — בגלל מיון פעיל.

refreshRow fell back to a full renderView whenever a sort was active, for any
change at all. But a sort only moves a row when the value it sorts BY is the one
that changed: sorted by one column and editing another, the row stays exactly
where it is. Rebuilding anyway threw away every group on the board and had them
re-measured from their height estimates — the flicker across the whole screen
after every status change.

Measured on a real board over the devtools protocol, same session, alternating
between the two conditions so it could not be drift:

    OLD (what QA runs)  fullRebuilds=1  maxHeightChange=-60px
    NEW (the fix)       fullRebuilds=0  maxHeightChange=0px
    OLD again           fullRebuilds=1  maxHeightChange=-60px

The paths that genuinely need the whole board are untouched: a row that has to
move because the sort key changed, a row the filter now excludes, a change that
affects more than one row, and a patch that could not be applied.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "sorted_board_does_not_rebuild.mjs"


def test_a_sorted_board_is_not_rebuilt_for_an_unrelated_column():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
