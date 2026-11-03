"""במצב סינון לא מופיעות קבוצות שאין תחתיהן רשומות.

groupsOf handed vTable every group the board has, with whatever matched the
filter attached to it — so a board of twelve groups holding two results drew
ten headings, ten rows of column names and ten "add item" lines over nothing,
with the two results somewhere in the middle. On screen that reads as a filter
that did not work.

A group with nothing in it is still part of the board's structure, so it is
drawn when no filter is on and comes straight back when one is cleared. The
line the rule is drawn along is NARROWING, not "the toolbar was touched": a
sort — the toolbar's own or a column header's — reorders the rows the board
already holds and removes none of them, so it must never take a group off the
screen. `filtersActive` could not be reused for this precisely because it
counts `f.sort`.

Two consequences come with hiding them, and the harness pins both. The groups
on screen are no longer the board's full order, and `/api/groups/reorder` is
told the whole sequence — so dragging three visible groups would file the nine
hidden ones wherever their old positions collided, and the grip is therefore
not drawn while a filter is on. And "הוסף קבוצה" would create a group that is
empty, hence immediately invisible, so it is not offered either.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "filter_hides_empty_groups.mjs"
INDEX = ROOT / "frontend" / "index.html"


def test_a_filtered_board_drops_the_groups_that_matched_nothing():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_rule_lives_in_groupsof_and_nowhere_else():
    """Every view that groups by the board's own groups goes through groupsOf.
    A second copy of the rule in one of them is the one that would drift."""
    src = INDEX.read_text(encoding="utf-8")
    i = src.index("function groupsOf(){")
    body = src[i:src.index("\n}", i)]
    assert "boardIsNarrowed()" in body, body
    # ...and it must be the narrowing predicate, never the one that counts a sort
    assert "filtersActive()" not in body, body
