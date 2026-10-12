"""הוספת פריט — הפריט החדש תמיד נראה, גם כשהלוח מסונן.

A new item answers almost no filter: nobody is assigned to it, it has no
priority, no link, no status anyone chose, and its title is a placeholder. With
a filter or a search active it was therefore created and hidden in the same
breath — no row appeared, the inline rename had nothing to open, and the only
thing left to do was click again, which made a second one. The board collected
two items called "פריט חדש" five seconds apart, both still carrying the
placeholder name because neither was ever on screen to be renamed.

Runs the real openNewItem, applyFilters and filtersActive out of index.html
under node, the same way tests/test_primary_env_entry.py does; the harness names
the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "new_item_visible.mjs"


def test_a_new_item_is_visible_whatever_the_board_is_filtered_to():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
