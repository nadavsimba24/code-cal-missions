"""Collapsed groups can be dragged into order.

A group in its collapsed state is a name and nothing else, and the gap that
separated it from the next group was margin — space belonging to no element.
Almost half of every slot on a folded board therefore hit-tested to the board
rather than to a group, so a drag answered only over the names and went dead in
between. The gap is the group's own padding now: identical spacing, and a slot
that responds along its whole height.

The harness reads the rules out of index.html under node and names the failing
case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "group_drag_collapsed.mjs"


def test_a_collapsed_group_owns_the_space_it_is_dropped_into():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
