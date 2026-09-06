"""The "סביבה חדשה" dialog.

Creating an environment was a native `prompt()` for the name, so the icon and
the colour — both of which POST /api/environments accepts, and one of which the
switcher shows on every row — were only ever whatever the server picked. The
dialog now asks for all three, in the same shape as the new-board modal, and
opens on the very colour the server would have assigned so that not choosing
changes nothing.

Runs the real Env object out of index.html against a stub DOM, the same way
tests/test_item_col_shrink.py does; the harness names the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "new_environment_dialog.mjs"


def test_the_new_environment_dialog_asks_for_and_sends_all_three():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
