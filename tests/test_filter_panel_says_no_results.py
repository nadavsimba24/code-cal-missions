"""חלון הסינון מסתיר את מצב "אין תוצאות" — אז הוא אומר אותו בעצמו.

The filter panel hangs from the toolbar — position:absolute, up to 74vh of it,
z-index 120 — directly over the board area. The board's own answer to a cut
that matches nothing is rendered into that same area by noMatchHTML(), so
somebody who narrows a filter down to nothing while the panel is open sees a
strip of columns and no answer at all: the one moment the board has something
to say is the one moment it is covered.

The panel now carries the notice as well, with the same way out, and both come
from one function — two copies would be two wordings a week from now.

The line an empty board draws is kept: a board with no items is not a failed
filter, and saying "אין תוצאות" over one sends somebody looking for a filter
to clear that was never on.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def test_the_panel_really_does_sit_over_the_board():
    """The premise. If the panel ever stops overlaying the board, the notice
    inside it becomes a duplicate and this is where that is noticed."""
    src = INDEX.read_text(encoding="utf-8")
    pop = next(l for l in src.splitlines() if l.startswith(".tb-pop{"))
    assert "position:absolute" in pop and "z-index:120" in pop, pop
    wide = next(l for l in src.splitlines() if l.startswith(".tb-pop-wide{"))
    assert "max-height:74vh" in wide, wide


def test_the_board_state_and_the_panel_share_one_way_out():
    """noMatchHTML and the panel must not drift into two different promises."""
    src = INDEX.read_text(encoding="utf-8")
    assert src.count("function clearCutAction(") == 1
    # the board's own state asks for it…
    nm = src[src.index("function noMatchHTML()"):]
    nm = nm[:nm.index("\n/*")]
    assert "clearCutAction()" in nm, nm
    # …and so does the panel, only with its own class
    assert "clearCutAction('qf-none-act')" in src
    # neither builds a button of its own any more
    assert nm.count("<button") == 0, nm


def test_the_notice_is_styled_in_the_products_palette():
    """No purple, and orange rather than red: an over-narrow filter is an
    answer, not an error."""
    src = INDEX.read_text(encoding="utf-8")

    def rule_of(sel):
        """The whole declaration — these span several lines."""
        i = src.index(sel)
        return src[i:src.index("}", i) + 1]

    rule = rule_of(".qf-none{")
    assert "var(--orange)" in rule, rule
    # RTL-first: the way out sits at the end of the line, stated logically
    assert "margin-inline-start" in rule_of(".qf-none-act{")
    for bad in ("purple", "#6366f1", "#7b3fe4", "left:", "right:"):
        assert bad not in rule, (bad, rule)


def test_the_panel_says_it(client, admin_id):
    """Driven harness: tests/frontend/filter_panel_says_no_results.mjs.

    Verified to fail: make cutMatchesNothing() answer true on an empty board
    and one case goes red; give the panel its own wording instead of
    clearCutAction and two more do.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "filter_panel_says_no_results.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
