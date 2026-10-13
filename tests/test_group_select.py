"""A checkbox at the group level — the one every item row already had.

Selecting a group of items meant ticking them one at a time, so "move these
twelve to another group" was twelve clicks before the move. The group header
carries the same box now, with the third state two states cannot express: all
of the group, none of it, or some — which is what ticking one row leaves it in.

Run out of index.html under node, like the other frontend harnesses. What is
pinned is the arithmetic and what lands in the selection: the box covers the
items the group is drawing (so a filter applies), never one this person may not
edit, and the group boxes are re-read off the selection rather than guessed at.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "group_select.mjs"


def test_a_group_can_be_selected_in_one_click():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
