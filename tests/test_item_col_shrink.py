"""On a phone the pinned item column gives room back as you scroll across.

It opens at full width — the board has to be readable before it is navigable —
and yields at most 40% of that width as the user scrolls sideways to reach the
other columns. Exercised by running the real syncItemColWidth under node, the
same way tests/test_selection_bar.py does; the harness names the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "item_col_shrink.mjs"


def test_the_item_column_yields_at_most_forty_percent():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
