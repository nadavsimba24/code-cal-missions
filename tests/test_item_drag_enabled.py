"""What switches item drag off — and what must not.

An item is grabbed by the row itself, so on a touch screen the drag gesture and
the scroll swipe are the same press-and-move; that is the reason the rule
exists. The rule was written as "narrow window", which is a different question.
A browser zoomed to 175% on a 1440px screen reports 823 CSS pixels, and a
split-screen window reports fewer — so item drag switched itself off on a
desktop, with a mouse, and said nothing about why.

Also guards the date cell: its invisible input covers the whole cell, and the
row's drag filter skips anything matching .cc-inp, so an input that can be a
click target makes the row unliftable from there.

Runs the real isTouch under node and reads the rules out of index.html, the
same way tests/test_item_col_shrink.py does; the harness names the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "item_drag_enabled.mjs"


def test_item_drag_follows_the_pointer_not_the_window_width():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
