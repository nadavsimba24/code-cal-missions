"""העברת בחירה לקבוצה — בקשה אחת מהדפדפן, בלי לשאוב את הלוח מחדש.

The slowness was in the client as much as the server: a round trip per item and
then a refetch of the whole board. Runs the real bulkMoveToGroup out of
index.html under node; the harness names the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "bulk_move_group.mjs"


def test_moving_a_selection_is_one_request_and_no_refetch():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
