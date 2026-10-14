"""משתמש לא פעיל לא מוצע באף בורר במסך.

The server refuses to invite, tag or name a deactivated account
(tests/test_inactive_user_is_not_offered.py). This harness covers the screen's
half: the lists the page builds itself must not offer somebody the server will
refuse — the people pickers (assignee circles, people cells, the @-menu, the
new-item form), the person field of an automation and its condition, and the
per-user item/column override rows. Each keeps anyone who already holds a value
so an old tag or grant stays clearable, and the member screens badge a
deactivated member so it is clear why they are in no picker.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "inactive_user_pickers.mjs"


def test_no_picker_offers_a_deactivated_user():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
