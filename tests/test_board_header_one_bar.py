"""The board header is two rows, not three.

Opening a board cost some 170px of chrome before the first item of it was on
screen — a title line, a line of view tabs carrying nothing else, and a separate
strip of actions below. On a page whose whole point is the table underneath,
that is two rows of nothing.

The tabs and the actions share one bar now: views at the start, search, filter
and "פריט חדש" at the far end. What this pins is that the saving does not turn
into a bug — the toolbar stays inside the header, the tab strip is never the
thing that shrinks when the row is crowded, and a phone gets its two stacked
rows back, because a full-width view picker beside a toolbar is unusable.

The harness reads the markup and the rules out of index.html under node and
names the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "board_header_one_bar.mjs"


def test_the_view_tabs_and_the_board_actions_share_one_bar():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
