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


def test_a_click_inside_the_panel_does_not_close_it():
    """The panel redraws itself on every value picked, which replaces the very
    element that was clicked. The "did this click land outside?" listener ran
    afterwards, in the bubble phase, found a detached node, read it as outside
    and shut the panel — so it closed the moment it was used.

    Asked in the CAPTURE phase the element is still where it was clicked. That
    is the only moment the answer is reliable, and it covers a keyboard Enter
    on a focused value too, where there is no mousedown to go by."""
    assert "let _popInside=false;" in SRC, "the inside/outside answer is no longer kept"
    i = SRC.index("let _popInside=false;")
    wiring = SRC[i:i + 420]
    assert "},true);" in wiring, \
        "the inside/outside question is asked after the redraw again — the panel will shut itself"
    assert "if(!_popInside)closePops()" in wiring


def test_the_panel_says_how_much_of_the_board_is_showing():
    """"מציג 12 מתוך 155 פריטים" is the sentence the whole panel is in service
    of. On a board the server filters in pages the browser holds one page, so
    it says what it knows instead of printing the page's number as the
    board's."""
    assert "function qfShowing(" in SRC
    i = SRC.index("function qfShowing(")
    body = SRC[i:SRC.index("\n}", i)]
    assert "Paged.on" in body, "a paged board would report its page as the whole board"


def test_the_counts_are_skipped_rather_than_guessed():
    """A number beside a value is only worth printing when it is the board's.
    Too many rows to count in a popup, or a board the server is filtering, and
    there is no number — the reference shows a dash in exactly those places."""
    i = SRC.index("function qfCounts(")
    body = SRC[i:SRC.index("\n}\n", i)]
    assert "Paged.on" in body and "QF_COUNT_MAX" in body, \
        "the counts are computed where they cannot be right"


def test_the_strip_can_be_moved_without_a_trackpad():
    """A strip that only answers to a two-finger swipe reads as a panel with
    three columns in it and no more. An arrow at each end, shown only when
    there is something past it, and a scrollbar that can be seen and dragged."""
    assert "function qfScroll(" in SRC and "function qfArrows(" in SRC
    assert 'class="qf-arr prev"' in SRC and 'class="qf-arr next"' in SRC
    assert "::-webkit-scrollbar-thumb" in SRC, "the strip's scrollbar is invisible again"


def test_a_pick_does_not_throw_her_back_to_the_first_column():
    """The panel redraws on every value picked. Starting the strip over would
    move the column she is working in out from under her."""
    assert "function qfRestore(" in SRC
    i = SRC.index("function qfRestore(")
    body = SRC[i:SRC.index("\n}", i)]
    assert "scrollBehavior='auto'" in body, \
        "restoring the position animates, so a pick slides the strip about"
    assert "qfRestore();" in SRC, "the restore is never called after a redraw"


def test_the_panel_opens_at_a_size_that_fits():
    """It opened at 920px — most of a laptop screen for something read in a
    glance — and could then run off the edge with no way to move it."""
    i = SRC.index(".tb-pop-wide.tb-pop-qf{")
    rule = SRC[i:SRC.index("}", i)]
    assert "620px" in rule and "max-width:calc(100vw" in rule, rule
