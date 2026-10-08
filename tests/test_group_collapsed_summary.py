"""What a group says about itself once it is folded shut.

Collapsed, a group shows neither its rows nor its progress bar — the header is
all that is left, and a bare "12" is not what someone who just folded a group
away still wants to know. Closed, a second line appears under the group's name:

    פתוח
    83 פריטים / 10 תתי־פריטים

The sub-items are counted even though they sit a level down: folding the group
takes the whole subtree off the screen, so counting only the parents understates
the group by however much work hangs beneath them.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "group_collapsed_summary.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_collapsed_group_reports_items_and_subitems():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_open_group_is_unchanged():
    """An open group keeps the plain count it always had — the summary is for
    the state where the rows are gone, and showing both would be noise on every
    board."""
    assert ".group-head .g-sum{display:none" in SRC, \
        "the summary shows while the group is open too"
    assert '<span class="g-count">${g.tasks.length}</span>' in SRC, \
        "the open group lost its count"


def test_the_sub_items_are_read_from_the_field_the_rows_are_drawn_from():
    """itemRow draws sub-rows from t.subtasks. A summary counting anything else
    would disagree with the rows the group shows when it is opened again."""
    assert "const subs=sortedSubs(t.subtasks||[]);" in SRC, \
        "itemRow no longer reads t.subtasks — the summary counts the wrong field"
    assert "tasks.reduce((a,t)=>a+((t.subtasks||[]).length),0)" in SRC
