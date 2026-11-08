"""‎"+ הוסף פריט" is a button the width of its own words.

The handler used to sit on the whole <tr>, so every pixel of the table row
answered a click — including the empty stretch past the last column, where
there is nothing written and nothing suggesting anything can be pressed. A
click aimed at nothing, or one that came down a few pixels below the last row,
filed a new item named "פריט חדש". The target is now the label itself, for the
item add-row and the sub-item one alike, and the row no longer lights up as if
it answered a click.

Markup and a stylesheet rather than logic, so it is pinned by reading them:
there is no DOM here to click. The behaviour that follows the click is pinned
in tests/test_new_item_visible.py.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

ADD_ROW = re.search(r'<tr class="add-row".*?</tr>', SRC, re.S)
SUB_ADD_ROW = re.search(r'<tr class="sub-add-row".*?</tr>', SRC, re.S)


def test_the_add_row_itself_answers_nothing():
    """The <tr> is a row of the table, not a control. A handler on it is the
    whole bug: it makes the full width of the board clickable."""
    assert ADD_ROW, "the add-row markup moved"
    opening = ADD_ROW.group(0).split(">", 1)[0]
    assert "onclick" not in opening, opening
    assert SUB_ADD_ROW, "the sub-item add-row markup moved"
    sub_opening = SUB_ADD_ROW.group(0).split(">", 1)[0]
    assert "onclick" not in sub_opening, sub_opening


def test_the_cell_is_not_the_target_either():
    """A <td> spanning the rest of the columns is as wide as the row was."""
    for row in (ADD_ROW.group(0), SUB_ADD_ROW.group(0)):
        for cell in re.findall(r"<td[^>]*>", row):
            assert "onclick" not in cell, cell


def test_the_label_is_what_takes_the_click():
    add = ADD_ROW.group(0)
    assert 'class="add-item"' in add, add
    span = re.search(r"<span class=\"add-item\"[^>]*>", add).group(0)
    assert "openNewItem(" in span, span
    sub = SUB_ADD_ROW.group(0)
    sub_span = re.search(r"<span class=\"add-item\"[^>]*>", sub).group(0)
    assert "addSubItem(" in sub_span, sub_span


def test_the_label_can_be_reached_and_pressed_with_a_keyboard():
    """A <tr onclick> was never reachable by tab at all; a span standing in for
    a button has to say it is one and answer Enter and Space, or the control
    simply does not exist for somebody not using a mouse."""
    for row, fn in ((ADD_ROW.group(0), "openNewItem"), (SUB_ADD_ROW.group(0), "addSubItem")):
        span = re.search(r"<span class=\"add-item\"[^>]*>", row).group(0)
        assert 'role="button"' in span, span
        assert 'tabindex="0"' in span, span
        assert "onkeydown=" in span, span
        assert "'Enter'" in span and "' '" in span, span
        # without this, Space scrolls the board while it adds the item
        assert "preventDefault()" in span, span
        assert fn + "(" in span.split("onkeydown=", 1)[1], span


def test_the_row_no_longer_offers_itself():
    """Hover and cursor are the promise the click then keeps. Left on the row
    they promise something the row no longer does, which reads worse than the
    row-wide click did: a thing that lights up and then ignores you."""
    td_rule = re.search(r"^\.add-row td\{[^}]*\}", SRC, re.M).group(0)
    assert "cursor:pointer" not in td_rule, td_rule
    assert not re.search(r"^\.add-row:hover td\{", SRC, re.M), "row-wide hover colour is back"
    assert not re.search(r"^\.sub-add-row:hover \.sub-add-cell\{", SRC, re.M)
    sub_rule = re.search(r"^\.sub-add-cell\{[^}]*\}", SRC, re.M).group(0)
    assert "cursor:pointer" not in sub_rule, sub_rule
    label_rule = re.search(r"^\.add-item\{[^}]*\}", SRC, re.M | re.S).group(0)
    assert "cursor:pointer" in label_rule, label_rule
    assert re.search(r"^\.add-item:focus-visible\{", SRC, re.M), "no keyboard focus ring"


def test_the_label_keeps_the_rows_height():
    """The add-row's height feeds the estimate that holds a group's place
    before it is laid out (ROW_H_EST and the measured _est beside it). Padding
    on the label with no matching negative margin would grow every add-row by a
    few pixels and put the content below it back to jumping as it renders."""
    label_rule = re.search(r"^\.add-item\{[^}]*\}", SRC, re.M | re.S).group(0)
    pad = re.search(r"padding:(\d+)px (\d+)px", label_rule)
    assert pad, label_rule
    assert "margin-block:-" + pad.group(1) + "px" in label_rule, label_rule
    assert "margin-inline:-" + pad.group(2) + "px" in label_rule, label_rule
