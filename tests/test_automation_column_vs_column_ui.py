"""הבורר של "להשוות לעמודה אחרת" — driven harness.

The server side of comparing one column with another is pinned in
tests/test_automation_column_vs_column.py. This is about the screen that writes
such a rule: that the choice is offered exactly where the engine would accept
it — the kinds the capabilities service lists, a board that actually has a
second column of that kind, and never the column being asked about — and that
what the builder sends is the reference the server stores rather than a value
coerced into a number or a date.

Checked in tests/frontend/automation_column_vs_column.mjs, which runs the real
Automations object out of index.html rather than a copy of it.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_the_value_blank_can_name_a_second_column():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_column_vs_column.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
