"""A group has to say how tall it will be before anyone has laid it out.

Off-screen groups are skipped by `content-visibility` (see .group in the CSS),
and a skipped group occupies exactly what its estimate claims. Get the claim
wrong and the group changes size the moment it is scrolled towards — and
everything after it moves with it, which is what "the board jumps" is.

The estimate used to be one constant for the furniture, and a constant can
only be right for one shape of board. That is why it jumped on some boards and
not on others: a group whose number column has values in it draws a סה"כ row
under the rows, and an open sub-item panel is a whole nested table — neither
was counted. Run out of index.html under node.

The shape of the code is pinned in tests/test_board_paint_skips_offscreen.py;
this is the arithmetic.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "group_height_estimate.mjs"


def test_a_group_estimates_the_height_it_will_really_come_to():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
