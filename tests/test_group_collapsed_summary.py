"""What a group says about itself once it is folded shut.

Collapsed, a group shows neither its rows nor its progress bar — the header is
all that is left, and a bare "12" is not what someone who just folded a group
away still wants to know. Closed, a second line appears under the group's name:

    פתוח
    83 פריטים / 10 תתי־פריטים

The sub-items are counted even though they sit a level down: folding the group
takes the whole subtree off the screen, so counting only the parents understates
the group by however much work hangs beneath them.

The item half of that line is no longer counted off the rows either. The board
sends each group's size (group_counts), counted in the database through the
same permission filter as its own total, and a collapsed group on a paged board
states that — the rows in hand are a page, and "0 פריטים" over a group holding
a thousand items is the same untruth as an empty board, only small enough to be
believed. The sub-item half has no such number on the wire, so where the item
count is the server's and the rows are still arriving the line drops it rather
than printing a fragment beside a fact: "1033 פריטים / 0 תתי־פריטים" asserts
that the group has no sub-items, which nobody on that screen knows. A board
holding all of its rows, and a board narrowed by a filter, go on showing both
halves off the rows they are drawing.
"""
import pathlib
import re
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


def test_an_open_group_shows_a_plain_count_and_nothing_else():
    """An open group keeps the plain count it always had — the summary is for
    the state where the rows are gone, and showing both would be noise on every
    board.

    This asserted the literal `${g.tasks.length}` until the count stopped being
    the rows this browser holds: on a paged board that number is a page, and
    the header now prints the size the server counted (group_counts) instead.
    The check was pinning how the line was written rather than what it says,
    which is why a correct change broke it — so what is asked now is that the
    header still carries a count span with a value in it, on both headings (the
    board's groups and the synthetic "ללא קבוצה"), and that CSS still swaps the
    count for the summary on collapse and not before. Which number goes in it is
    run, not read, in group_collapsed_summary.mjs.
    """
    assert ".group-head .g-sum{display:none" in SRC, \
        "the summary shows while the group is open too"
    assert ".group-head.collapsed .g-count{display:none}" in SRC, \
        "the open group's count is hidden, or hidden in the wrong state"
    spans = re.findall(r'<span class="g-count">\$\{[^}]+\}</span>', SRC)
    assert len(spans) >= 2, f"the open group lost its count: {spans}"


def test_the_sub_items_are_read_from_the_field_the_rows_are_drawn_from():
    """itemRow draws sub-rows from t.subtasks. A summary counting anything else
    would disagree with the rows the group shows when it is opened again."""
    assert "const subs=sortedSubs(t.subtasks||[]);" in SRC, \
        "itemRow no longer reads t.subtasks — the summary counts the wrong field"
    assert "tasks.reduce((a,t)=>a+((t.subtasks||[]).length),0)" in SRC
