"""The search box finds an item by the number in its "מזהה פריט" column.

The id is the one thing about an item that travels outside the board: it is
what gets read out on the phone, pasted into a mail, quoted in a ticket, and
the column exists so it can be copied off a row. Searching the board for it
found nothing — the box looked at titles, descriptions, assignees and the names
of linked items, and never at the number.

It is eleven digits, so the query has to look like an id before it is treated
as one. Otherwise searching "5" matches nearly every item on the board (an id
with a 5 somewhere in it) and buries the item whose title has a 5 in it.

The harness runs the real applyFilters under node over a small board and names
the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "search_item_id.mjs"


def test_an_item_is_found_by_its_id():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
