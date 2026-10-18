"""חלון הפריט נסגר במעבר בין לוחות או בין סביבות.

The conversation, the files and the log are three tabs of one panel, opened
from one item. Switching board left it open: the panel of an item that is no
longer anywhere on screen, over a board it has nothing to do with. paintBoard
then rewrote the URL to #/board/<the new one>, so the address said one thing
and the panel showed another — and the next reload closed it without being
asked to, which is the app disagreeing with itself.

Two rules, and the second is what keeps the first from being destructive: the
panel closes where the board CHANGES, and nowhere else. Reopening the same
board — a revalidation, a deep link landing where you already are — leaves an
open conversation exactly as it was, with whatever is typed in it. Chat.close
saves the draft before clearing the item, so nothing typed is lost either way.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_one_function_closes_it_so_the_two_callers_cannot_drift():
    assert "function closeItemPanel()" in SRC
    m = re.search(r"function closeItemPanel\(\)\{(.*?)\n\}", SRC, re.S)
    assert m and "Chat.close()" in m.group(1)
    assert "Chat.taskId!=null" in m.group(1), \
        "it closes a panel that is not open, rewriting the URL for nothing"


def test_changing_board_closes_it_and_reopening_the_same_one_does_not():
    body = re.search(r"async function openBoard\(id\)\{(.*?)\n\}", SRC, re.S)
    assert body, "openBoard moved"
    body = body.group(1)
    assert "st.board.id!==id){ closeItemPanel()" in body, \
        "the panel closes on every openBoard, draft and all, even for the board already open"
    assert body.index("closeItemPanel()") < body.index("paintBoard(id)"), \
        "the old item's panel is still up while the new board is painted"


def test_changing_workspace_closes_it_too():
    sel = re.search(r"  select\(id\)\{(.*?)\},", SRC, re.S)
    assert sel, "Env.select moved"
    assert "closeItemPanel()" in sel.group(1)


def test_the_panel_really_closes_on_both():
    """Driven harness: tests/frontend/item_panel_closes.mjs.

    Verified to fail three ways: drop the call from openBoard and two cases go
    red; drop it from Env.select and two do; make it unconditional in
    openBoard — closing a conversation when the same board is merely reopened
    — and one does.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "item_panel_closes.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
