"""A list column's options are typed in a row inside the popover, not one
browser prompt() at a time.

The prompt closed the list behind every word, so a column of ten options was
ten trips through a modal. The field now stays open and Enter moves on to the
next word — which lets a second Enter arrive while the first save is in
flight. Each save sends the whole column list, so overlapping saves would let
the slower one drop the other's word; the harness pins that they are queued
and sent one at a time, and that nothing typed is lost.

Driven harness: tests/frontend/dropdown_options_typed_in_a_row.mjs.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "dropdown_options_typed_in_a_row.mjs"


def test_options_typed_one_after_another_all_reach_the_column():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
