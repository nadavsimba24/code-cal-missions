"""Drawing a board must not build what nobody can see.

The server half of the board-open cost is tests/test_board_open_is_one_pass.py.
This is the screen. Two things were being paid for on every single row:

* the sub-item panel — a table, a colgroup, and a header cell per column — was
  built and then hidden, for every row, including the rows with no sub-items;
* the column model was re-derived from the board's settings for every row that
  asked, three times a row.

On a real board of 687 items and 29 columns that is tens of thousands of
invisible elements and a couple of thousand redundant derivations, and it was
the larger half of the time it took to switch boards. Run out of index.html
under node.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "board_render_cost.mjs"


def test_a_board_draws_only_what_is_visible():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
