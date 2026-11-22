"""A rename of a list option waits its turn behind the column's other saves,
and a rename field that leaves the page is not taken as a rename.

Every option save sends the whole column, so the one that runs second wins:
an add or a deactivate started during a rename used to send the list from
before it, which the server read as deleting the new word — a 409 about an
option nobody deleted, or a column put back to the old word under cells that
already said the new one. And a redraw removes the focused rename field,
Chromium fires blur on it, and blur commits — so half-typed text was renamed
onto every item on the board.

Driven harness: tests/frontend/dropdown_rename_waits_its_turn.mjs.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "dropdown_rename_waits_its_turn.mjs"


def test_a_rename_and_the_saves_behind_it_go_one_at_a_time():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
