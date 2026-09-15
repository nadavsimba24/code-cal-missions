"""The dates inside an item's conversation carry their year.

A conversation can span years — an imported one certainly does — and "14.09,
12:34" on a message from two years ago reads as today.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "chat_date_year.mjs"


def test_the_conversation_states_the_year():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
