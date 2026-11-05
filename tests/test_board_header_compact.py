"""The board header is sized for a bar, not for a page heading.

Opening a board cost some 170px of chrome before the first item of it was on
screen — a 23px title set like a page heading, 18px of padding above it, 14px
under it, and two strips below padded to match. On a page whose whole point is
the table underneath, most of that was air.

The three rows stay three: the actions read better on a line of their own than
squeezed against the view tabs. What this pins is the part that is easy to undo
by accident — the paddings staying small, the action strip keeping the surface
and the rule that close the chrome off from the table, the order along it being
the order of the work (new item, search, filter, clear), and a phone getting a
strip that scrolls sideways rather than wrapping into another row of chrome.

The harness reads the markup and the rules out of index.html under node and
names the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "board_header_compact.mjs"


def test_the_board_header_is_sized_for_a_bar():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
