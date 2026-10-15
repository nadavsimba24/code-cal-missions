"""שינוי בעמודת תיבת-סימון נקרא ביומן כווי, לא כמילה "true".

A checkbox column stores `true` when ticked and `null` when not, and the log
printed both straight through: ticking a box read "— ← true". The English word
for a value in a Hebrew log, and an em-dash — which everywhere else in this log
means "nothing at all" — standing in for a box somebody deliberately cleared.

A checkbox has two states and no empty one, so both say what they are, and the
board log draws the tick on whichever side is ticked, in the same green the cell
itself uses (.cc-check is accent-coloured green). The words carry the meaning on
their own, so the row still reads if the icon font has not loaded.

Verified in a real browser against a real checkbox column before and after: the
rendered row went from `— ← true` to `☐ לא מסומן ← ☑ מסומן`.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "log_checkbox_reads_as_a_tick.mjs"


def test_a_checkbox_change_reads_as_a_tick():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
