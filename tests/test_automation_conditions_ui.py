"""The "רק אם" block in the create screen, run out of index.html under node.

The server half of two-condition rules is covered by
tests/test_automation_two_conditions.py. This covers the half that decides what
the server is ever asked to store: a condition reads as a phrase with its value
in place, one still missing its value never leaves the screen, and a rule with
no conditions sends none — which is what keeps every rule written before today
behaving exactly as it did.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "automation_conditions.mjs"


def test_the_conditions_block_builds_the_rule_it_shows():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
