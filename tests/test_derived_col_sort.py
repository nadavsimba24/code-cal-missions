"""Sorting the derived columns — the ones that hold no value of their own.

"מזהה פריט", "מועד יצירה", "יוצר הרשומה", נוסחה and שדה מראה read the item
itself or compute; nothing about them lives in `custom_fields`. The comparator
only looked there, so it scored every row the same — three items came back as
["", "", ""] — and the click landed on a list that could not move. The header
button was there and worked; there was simply nothing to sort by.

Runs the real customSortVal / sortVal / colCompare out of index.html under
node, the same way tests/test_item_col_shrink.py does; the harness names the
failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "derived_col_sort.mjs"


def test_the_derived_columns_sort_by_what_their_cells_show():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
