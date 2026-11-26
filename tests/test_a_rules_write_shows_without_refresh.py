"""A rule's write shows on the row without a refresh.

"כאשר הסטטוס משתנה, עדכן את «תאריך עדכון» להיום" ran on every change, and the
date was in the PATCH answer every time — but the grid read only group_id out
of that answer and left the rest to the live stream's automation.ran. Whenever
that event did not arrive (a paged board, a dropped stream) the stamp showed
only after F5, which reads as a rule that works once and then stops. The
server half is tests/test_a_status_change_stamps_todays_date.py; this is the
screen, run out of index.html under node.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "a_rules_write_shows_without_refresh.mjs"


def test_the_date_a_status_rule_wrote_is_on_the_row_at_once():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
