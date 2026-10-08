"""Tapping a board in the sidebar, on a phone.

Three different things sat on that one tap.

The drawer was dismissed on the last line of openBoard — after the board had
been fetched and drawn — so the tap did nothing visible until the network came
back, and a board that answered 403, or any render below it that threw, left
the drawer standing over the board it had just opened.

The sidebar reorders by dragging, and Sortable claims a touch gesture from the
first pixel: a tap that drifted became a drag and never opened anything, and a
finger scrolling the board list dragged a board instead.

And the row's ⋮ button is opacity:0 until :hover, which a finger never
delivers — invisible, and still taking every tap that landed on it.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "sidebar_tap_mobile.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_tap_opens_the_board_and_closes_the_drawer():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_close_comes_before_the_fetch():
    """Order is the whole fix: both lines are a call to the same function, and
    only their position says whether the drawer waits on the network."""
    body = re.search(r"async function openBoard\(id\)\{(.+?)\n\}", SRC, re.S).group(1)
    closed = body.index("closeSidebarMobile()")
    fetched = body.index("await api(")
    assert closed < fetched, "the drawer still waits for the board to arrive"


def test_the_sidebar_board_rows_open_the_board_through_it():
    """If a row ever stops going through openBoard it stops closing the drawer,
    and that is not visible from openBoard itself."""
    assert 'onclick="openBoard(${b.id})"' in SRC, \
        "the sidebar board row no longer calls openBoard"
