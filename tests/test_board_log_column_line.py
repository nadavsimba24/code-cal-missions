"""שורת לוג על מחיקת עמודה מדברת על הלוח, לא על פריט.

Every other line in the board log is about an item: it opens with the item's
name as a button that opens it. A column deletion has no item behind it — the
server sends it with task_id null and the board's name instead — so the row
has to draw a plain line there, and the words have to say that a COLUMN was
deleted before the generic "נמחק", which on a line carrying a board's name
would read as a deleted item.

The harness runs the real BoardLog.fieldLabel and fieldIcon out of index.html
and reads the row template and the .lg-board rules beside them. The server
half of this is pinned by tests/test_board_log_records_column_deletion.py.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "board_log_column_line.mjs"


def test_a_deleted_column_reads_as_a_column_and_opens_nothing():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
