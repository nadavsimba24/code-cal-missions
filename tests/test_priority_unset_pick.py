"""The grey "טרם הוגדר" has to be pickable in the priority column too.

The server half is tests/test_priority_back_to_unset.py. This is the screen:
the built-in priority column's picker offering the grey default, ticking it when
that is where the item is, and sending the one pair the API reads as "nobody has
chosen" — an explicit null plus the flag. It also pins the half the two columns
do NOT share: a cleared priority falls back to `medium` and a cleared status to
`todo`, from the one code path that now serves both. Run out of index.html under
node.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "priority_unset_pick.mjs"


def test_the_priority_picker_offers_the_grey_default():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
