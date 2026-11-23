"""תפריט עמודה של תת-פריט מציע את מה שתפריט העמודה של הפריט מציע.

The sub-item header's "..." menu was written on its own and offered rename,
"בחר עמודות תת-פריט" and delete — nothing about the column's type. A number
column under an item could not have its display set from where it is shown,
and no sub-item column could change type.

The type-specific options now come from one function, colTypeOptsHTML, which
both menus call, so they cannot drift apart again. "בחר עמודות תת-פריט" picks
which columns sub-items show at all; it was never about the column whose menu
it sat in, and it lives once, on the gear in the "תת-פריט" header.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_the_sub_item_column_menu():
    """Driven harness: tests/frontend/a_sub_item_column_menu_offers_what_an_item_column_does.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "a_sub_item_column_menu_offers_what_an_item_column_does.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
