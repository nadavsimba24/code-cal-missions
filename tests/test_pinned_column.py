"""העמודה הנעוצה מציגה שמות פריטים — ולא שורות שנגללו לשם.

With enough columns the board scrolls sideways, and the item column stays at
the start of the viewport so a row never becomes an anonymous line of values.
`.tbl td.c-item` is sticky and carries a background of its own, repeated for
every state the row can be in, so the cells sliding beneath it do not show
through.

"+ הוסף פריט" had no such cell — it spanned the whole table in one — and now
has one: the label belongs where the item names are, and putting it there
costs nothing, because the label is all that row holds.

The sub-item wrapper got one too, and it has been taken back out. A row's
content starts after whatever cell precedes it, so a pinned cell as wide as
the פריט column pushed the whole sub-item panel out by that column's width —
280px by default, more where an admin has widened it. The sub-items ended up
indented a third of the way across the board, and that was asked to be undone.

The two cannot both be had. The panel's nesting indent is 46px, which is
INSIDE the pinned column's own 280px: it either begins there and is visible in
that strip while the board is scrolled sideways, or begins after the column
and is pushed out by its full width. The light indent is the one that was
asked for, and what shows in the strip is the panel in its own band of rows —
no item's name, since every item row has its own opaque pinned cell and goes
on covering whatever slides beneath it.

So the invariant here is NOT "every row begins in the pinned column". It is
narrower and still worth holding: every row that has something of its own to
show at the start edge keeps it pinned there.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_add_item_row_keeps_its_cell_in_the_pinned_column():
    """"+ הוסף פריט" is a label and nothing else, so pinning it costs no
    layout: it stays where the item names are instead of sliding out of the
    board with the rest of the row."""
    row = re.search(r"<tr class=\"add-row\"[^>]*>\s*<td[^>]*>", SRC)
    assert row and "c-item" in row.group(0), row and row.group(0)


def test_the_sub_item_wrapper_spans_the_table_and_is_meant_to():
    """Deliberately NOT pinned, and reverted to deliberately — see the module
    docstring. A pinned cell here is as wide as the פריט column and pushes the
    whole panel out by it, which is the 280px of indent this row got rid of.

    Pinned again by someone reading only the rule above, the indent comes
    straight back; that is what this case is here to stop."""
    row = re.search(r"<tr class=\"sub-wrap\"[^>]*>\s*<td[^>]*>", SRC)
    assert row, "the sub-item wrapper moved"
    assert "c-item" not in row.group(0), \
        "the sub-item panel is pinned again, which indents it by the item column's width"
    assert 'colspan="${totalCols()+1}"' in SRC, \
        "the wrapper no longer spans the whole table"


def test_the_panel_keeps_its_light_nesting_indent():
    """46px from the table's start, which is what it has always been and what
    was asked for back. Read as the number, so a change to it is a change this
    case notices."""
    m = re.search(r"\.sub-panel\{([^}]*)\}", SRC)
    assert m, ".sub-panel moved"
    assert "margin-inline-start:46px" in m.group(1), m.group(1)
    assert "sub-wrap-cell" in SRC


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
