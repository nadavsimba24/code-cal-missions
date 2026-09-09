"""A group being dragged shows where it will land.

Sortable leaves the dragged group in the list as its own placeholder, so the
landing slot is already the right shape and follows the pointer. It wore only a
fade, which is easy to miss against a board of groups and nearly invisible on a
folded one, where a group is a name and nothing more. The slot is now outlined
and tinted — the same dashed frame "+ הוסף קבוצה" wears — with the group's own
content faded inside it.

The harness reads the rules out of index.html under node, including the two the
marking has to outweigh (the blanket placeholder fade, and the lift that belongs
to the copy following the cursor), and names the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "group_drop_marker.mjs"


def test_the_landing_slot_is_marked_while_the_group_is_in_the_air():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
