"""מחיקת קבוצה נשאלת כמו כל מחיקה אחרת, ואומרת למה כשהיא לא מתאפשרת.

Nothing ever stopped a group from being removed — the server deletes any of
them and detaches their items (test_group_delete_any.py). What made it look
otherwise was this one function: it asked with a native confirm(), the only
dialog in the app that was not ours, and a browser may suppress that. A
suppressed confirm() returns false, so pressing מחק did nothing at all and
explained none of it. Refusals were flattened to "שגיאה במחיקה" too, so a board
you may not edit read like a group that cannot be deleted.

The harness reads the function out of index.html under node and names the
failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "group_delete_dialog.mjs"


def test_the_delete_question_is_ours_and_a_refusal_carries_its_reason():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
