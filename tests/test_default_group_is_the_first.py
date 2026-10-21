"""Group — a new item goes into the board's FIRST group.

The "פריט חדש" button at the top of a board does not ask which group; it picks
one. It used to pick whichever group carried the backlog status — "בתכנון" on a
board whose groups came out of the box — and fell back to the first group only
when no group had that status. So on every board where the first group is
something else (one reordered, one imported, one built by hand) the button filed
the item somewhere down the page, under a heading nobody had pointed at, while
the place it was asked for was the top.

The order of the groups on screen is an order somebody arranged. "The first one"
is the only reading of it the board itself offers, and it is now the whole rule.

A group's own "+ הוסף פריט" names its group and never goes through this.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_first_group_is_the_default():
    """Driven harness: tests/frontend/default_group_is_the_first.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "default_group_is_the_first.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_no_status_decides_where_a_new_item_lands():
    """The rule is the order, and nothing else. A status test creeping back into
    this function is the old behaviour returning under a new name."""
    i = SRC.index("function defaultGroupId()")
    body = SRC[i:SRC.index("\n}", i)]
    assert "backlog" not in body, \
        "defaultGroupId is choosing by status again instead of by order"
    assert "position" in body, "defaultGroupId no longer reads the groups' order"


def test_the_agent_puts_an_item_in_the_same_place():
    """Two ways to add an item, one answer. The agent's own fallback already
    took the board's first group by position; the button now agrees with it."""
    main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert "db.query(Group).filter(Group.board_id == board_id).order_by(Group.position).first()" in main, \
        "the agent no longer falls back to the board's first group"
