"""מצבים והודעות, ונגישות הרצועה.

The five states are driven by tests/frontend/view_states.mjs. What is pinned
here is the source-level half: the things a harness cannot see because they
live in CSS or in the document's own attributes.

Three of those are requirements that what I had already written broke, which
is why they are cases rather than a note:

  no dependence on hover on mobile — the per-view menu was revealed on hover,
    and a touch screen has none. The menu was reachable only by opening the
    view first, which is the one thing somebody renaming or deleting a tab
    has not asked to do.
  44x44 touch targets — the menu button was 22x22, under half the minimum.
  a visible focus ring — the board is operable from the keyboard only if the
    caret can be seen while it moves.

Verified to fail: remove the coarse-pointer block and two go red; drop the
focus-visible rule and one does.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_nothing_added_to_the_strip_depends_on_hover_on_a_touch_screen():
    """A touch screen has no hover. A control revealed by it is a control that
    does not exist there."""
    m = re.search(r"@media \(hover:none\),\(pointer:coarse\)\{(.*?)\n\}", SRC, re.S)
    assert m, "there is no coarse-pointer block for the view strip"
    body = m.group(1)
    assert ".tab-view-menu{opacity:1" in body, \
        "the per-view menu is still hidden until hover on touch"


def test_every_touch_target_added_here_is_at_least_44px():
    """WCAG 2.5.5. The menu button was 22x22 — under half."""
    m = re.search(r"@media \(hover:none\),\(pointer:coarse\)\{(.*?)\n\}", SRC, re.S)
    body = m.group(1)
    # The all-views picker and its rows were removed from the strip, so the
    # controls left to size are the per-view menu and the "+" menu's action
    # row. A case naming a control that no longer exists is a case nobody is
    # checking, dressed as one that passes.
    for sel in (".tab-view-menu", ".pop-row-act"):
        assert sel in body, f"{sel} has no touch sizing"
    assert "44px" in body, body


def test_the_focus_ring_is_visible_on_what_was_added():
    """Operable from the keyboard means the caret can be SEEN while it moves."""
    assert re.search(r"\.tab-view-menu:focus-visible[^{]*\{[^}]*outline:2px solid", SRC), \
        "the strip's controls have no visible focus ring"
    assert ".pop-row-act:focus-visible" in SRC, "the + menu's action has no ring"


def test_the_states_announce_themselves():
    """A state that replaces the whole board has to reach a screen reader —
    silently swapping the table for a message is a change nobody is told
    about."""
    m = re.search(r"\nfunction stateHTML\((.*?)\n\}", SRC, re.S)
    assert m and 'role="status"' in m.group(1), "the board states are not announced"
    assert re.search(r"\n  failedHTML\(\)\{.*?role=\"alert\"", SRC, re.S), \
        "a failed save is not announced"


def test_the_page_is_rtl_and_the_strip_uses_logical_properties():
    """Hebrew-first. A view strip written with left/right rather than
    start/end reverses the moment the document does."""
    assert 'dir="rtl"' in SRC or "dir='rtl'" in SRC
    block = SRC[SRC.index("/* ===== saved-view tabs"):SRC.index("/* ===== board screen")]
    for bad in ("margin-left:", "margin-right:", "padding-left:", "padding-right:"):
        assert bad not in block, f"{bad} in the view strip — use the logical property"


def test_a_failed_save_never_advances_what_unsaved_is_measured_against():
    """The source side of the harness case, because this is the worst bug
    available here: the screen says saved, the next person opens the tab and
    finds the old cut, and the adjustments are gone from the one place they
    still existed."""
    m = re.search(r"\n  async update\(\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "Views.update moved"
    body = m.group(1)
    base = body.index("this.base=JSON.stringify")
    caught = body.index("}catch(")
    assert base < caught, "base is advanced outside the success path"
    assert "finally" not in body, "a finally here would advance it on failure too"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_the_states_harness():
    r = subprocess.run(["node", str(ROOT / "tests" / "frontend" / "view_states.mjs")],
                       capture_output=True, text=True)
    print(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
