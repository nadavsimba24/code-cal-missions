"""עמודת "כניסה אחרונה" מוצגת בשעון ישראל.

The server half is tests/test_login_times_say_which_zone.py — the API marks its
timestamps UTC instead of sending them bare. This is the screen's half: a bare
timestamp is still read as UTC, so an old cached payload cannot disagree with a
fresh one, and the value is formatted in Asia/Jerusalem so the column reads
Israel time wherever the viewer's machine is set.

The zone is applied, not an offset: a January login reads +2 and an October one
+3, which a hardcoded three hours would get wrong for half the year.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "login_time_is_israel_time.mjs"


def test_the_last_login_column_reads_in_israel_time():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
