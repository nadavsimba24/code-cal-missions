"""ריחוף מעל תא מציג את הערך במלואו — מהר, ובכל מקום בתא.

The grid gives every column one line as wide as the column, so a name or a
text value longer than that is simply not readable in the table. Hovering is
where the rest of it lives.

Two things about that went wrong before this was pinned, and both of them
looked identical from the outside — "the hover does nothing":

1. The value sat on the <span> holding the text, and the name cell is mostly
   not the text: a checkbox, a menu, the sub-item caret, a badge and the chat
   button share it. A pointer anywhere else in the cell found no value at all.
   So the CELL carries it too, not only the text inside it.

2. It was the browser's own `title`, which appears after about a second and a
   half. That is long enough to read as broken, and nothing in CSS or JS can
   shorten it. The tooltip is ours now, drawn after 150ms.

Which is why the value travels in `data-tipf` and not in `title`: an element
carrying both would answer twice — ours at once, and the browser's a second
later, on top of it.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_hover_tooltip_behaves():
    """Driven harness: tests/frontend/cell_hover_full_value.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "cell_hover_full_value.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_value_is_escaped_into_the_tooltip():
    """An item named <img onerror=…> is stored XSS the moment a tooltip

    trusts it. The box is built with innerHTML, so both the value and the hint
    go through esc() — and the attribute the value is read back out of is
    written with esc() too.
    """
    m = re.search(r"function cellTipShow\(el\)\{(.*?)\n\}", SRC, re.S)
    assert m, "cellTipShow is gone — the tooltip is drawn somewhere else now"
    body = m.group(1)
    assert "box.innerHTML=esc(txt)" in body
    assert "${esc(hint)}" in body


def test_the_browsers_own_tooltip_is_not_left_on_the_same_element():
    """Both would fire — ours at 150ms and the browser's a second later."""
    # the "+ הוסף פריט" row is a c-item cell too, and it has no value to show
    cells = [c for c in re.findall(r"<td class=\"c-item\"[^>]*>", SRC)
             if "itemRowMenu" in c]
    assert cells, "the item row no longer opens its menu from the name cell"
    for frag in cells:
        assert "data-tipf=" in frag and "title=" not in frag, frag
    for frag in re.findall(r"<span class=\"item-title editable\"[^>]*>", SRC):
        assert "data-tipf=" in frag and "title=" not in frag, frag
