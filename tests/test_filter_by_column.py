"""Group — the filter button opens the board's own columns.

It used to open three fixed sections — אדם, סטטוס, עדיפות. Those are three of a
board's columns and not the board's columns: everything somebody had added to
their own board, which is most of what a board is, could only be filtered
through the advanced builder — pick a column, pick an operator, type a value.
For "show me what is תקוע" that is a sentence to build in order to ask a
question with one answer.

The panel now lists the columns of the board being looked at, each opening to
the values it holds: a status column its own words in its own colours, a people
column the board's members with "אני" first, a date column the spans, and ריק /
אינו ריק for any column at all.

What it writes is the SAME condition tree the advanced builder edits and the
server evaluates (backend/filter_ast.py). That is the point rather than an
implementation detail: one model narrows a small board in the browser and a
large one in the database, travels inside a saved view, and shows up in the
advanced builder as the conditions it is. A second filter model beside it would
have had to be taught all of that again.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_panel_writes_the_tree_correctly():
    """Driven harness: tests/frontend/filter_by_column.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "filter_by_column.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_panel_is_built_from_the_board_s_columns():
    """advFields() is the list of columns the board can be asked about, and it
    is what the panel is drawn from. Drawn from anything else — the raw column
    list, say — it would offer columns this person may not see, and a filter is
    a question whose answer is the rows that survive it."""
    i = SRC.index("function colFilterHTML()")
    body = SRC[i:SRC.index("\n}", i)]
    assert "advFields()" in body, "the filter panel is no longer built from the board's columns"


def test_the_three_fixed_sections_are_gone():
    """Status and אחראים are columns now, offered beside every other column.
    Leaving the old sections in would mean two places that filter the same
    thing, disagreeing the moment either is used."""
    assert "setStatusFilter" not in SRC and "setPriorityFilter" not in SRC, \
        "the old single-value status/priority filters are back"
    assert "toggleFilterPerson" not in SRC, "the old people section is back"


def test_the_old_fields_still_narrow_a_board():
    """A saved view made before the panel carries st.filters.status/.people.
    They must keep working — and the panel shows them as picked, so a board
    that is filtering never looks like one that is not."""
    assert "function advLegacyPicks(" in SRC, "old saved views no longer show as picked"
    i = SRC.index("function applyFilters(")
    body = SRC[i:SRC.index("\n}", i)]
    assert "f.status" in body and "f.people.length" in body, \
        "applyFilters stopped honouring the fields old saved views carry"


def test_the_filter_travels_to_the_server():
    """Both ways of building it ask the server the same question — the local
    answer is instant, the server's is the authority and the only one that can
    answer for a board too large to hold in the browser."""
    assert "async function advAskServer()" in SRC
    i = SRC.index("function advChanged()")
    assert "advAskServer()" in SRC[i:i + 400], "a pick in the panel never reaches the server"
