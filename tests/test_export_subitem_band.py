"""הגריד המיוצא: לכל רצף תתי-פריטים כותרת משלו.

Sub-items have a column structure that is not a subset of the item's — a board
can give them columns that exist nowhere else. The grid laid every sub-item out
under the item's headers and wrote a value only where the two structures shared
a column id, so exactly those sub-item-only columns were dropped from the file,
with nothing in it to say they had been.

The harness runs the real exportGrid under node over a stub board whose
sub-items carry such a column, and names the failing case. The server's half —
writing the band, marking it, folding it into its item — is in
tests/test_board_export_conversation.py.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "export_subitem_band.mjs"


def test_sub_item_columns_reach_the_exported_grid():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
