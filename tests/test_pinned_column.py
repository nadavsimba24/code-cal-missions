"""העמודה הנעוצה מציגה שמות פריטים — ולא שורות שנגללו לשם.

With enough columns the board scrolls sideways, and the item column stays at
the start of the viewport so a row never becomes an anonymous line of values.
`.tbl td.c-item` is sticky and carries a background of its own, repeated for
every state the row can be in, so the cells sliding beneath it do not show
through.

Two rows had no such cell. "+ הוסף פריט" and the sub-item panel's wrapper each
spanned the whole table in a single cell, so nothing in them was pinned: the
panel began 46px from the table's start — inside the pinned column's strip —
and slid sideways across it in plain view behind the item names, which is the
one thing a pinned column must never show.

Covering the strip was the wrong fix: the cover would hide the start of the
panel at rest as well, and the start of the panel is the sub-item names. So
each of those rows gets the column's own cell, and the panel begins after it —
the strip holds item names and nothing else, and the panel scrolls under it and
out of sight.

What is pinned here is the invariant rather than the two rows: every row the
board draws begins with a cell in the pinned column.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_no_row_in_the_board_table_spans_the_pinned_column():
    """The source side of the invariant: a row written as one full-width cell
    is a row with nothing pinned, and that is how this bug was introduced
    twice. `totalCols()+1` is the whole colgroup — in a row that starts in the
    pinned column it has to be one less."""
    for row in re.findall(r"<tr class=\"(?:add-row|sub-wrap)\"[^>]*>\s*<td[^>]*>", SRC):
        assert "c-item" in row, row
    assert 'colspan="${totalCols()+1}"' not in SRC, \
        "a row spans the whole table again, which leaves the pinned column empty in it"


def test_the_panel_is_indented_from_the_column_and_not_over_it():
    """46px of nesting indent, measured from where the pinned column ends — the
    panel used to be indented from the table's start, which put most of it
    inside the strip."""
    m = re.search(r"\.sub-panel\{([^}]*)\}", SRC)
    assert m, ".sub-panel moved"
    assert "margin-inline-start:46px" in m.group(1), m.group(1)
    assert "sub-wrap-cell" in SRC and 'colspan="${totalCols()}"' in SRC


def test_the_pinned_column_reaches_the_edge_the_board_is_cut_off_at():
    """The strip at the start edge, measured rather than guessed.

    A sticky cell inside a scroll container comes to rest against the
    container's CONTENT edge; the container clips at its PADDING edge. Between
    the two is a strip as wide as #view's inline padding — 26px on a desktop
    board — which the pinned column did not reach and the scrolling columns
    did: the column sliding under it peeked out there, a sliver of a row that
    had been scrolled away. Measured in Chrome on a scrolled board: the pinned
    cell ended at 990, the view clipped at 1016, and the cell behind it ran
    979..1129.

    So the rest position is pulled out by exactly that padding, and the padding
    is a variable because there are three of it (the base, the desktop
    refinement, the phone) and a hardcoded -26px would be wrong on two of them.
    """
    assert len(re.findall(r"#view\{[^}]*--view-pad:\s*\d+px", SRC)) == 3, \
        "a #view padding that does not declare --view-pad leaves the strip open there"
    assert len(re.findall(r"#view\{(?:[^}]*?)padding:0 var\(--view-pad\)", SRC)) == 3
    for sel in (r"\.tbl th\[data-fixed\]\{inset-inline-start:calc\(-1 \* var\(--view-pad",
                r"\.tbl td\.c-item\{position:sticky;inset-inline-start:calc\(-1 \* var\(--view-pad",
                r"\.gh-in\{position:sticky;inset-inline-start:calc\(-1 \* var\(--view-pad"):
        assert re.search(sel, SRC), sel


def test_every_row_the_board_draws_starts_in_the_pinned_column():
    """Driven harness: tests/frontend/pinned_column.mjs.

    Verified to fail: put the sub-item panel back in a row of its own that
    spans the whole table and three cases go red; take the label out of the
    pinned cell in the add row and two do.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "pinned_column.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
