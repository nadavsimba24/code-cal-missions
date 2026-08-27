"""The board header sticks the same way on a phone as in a desktop browser.

Two separate things have to hold, and only one of them is about `position`:

  1. Nothing in the narrow-screen media query may unstick the group name or the
     column header row. Same rules, both widths.
  2. The container they stick to has to BE the screen. `100vh` on a phone is
     measured with the browser's URL bar retracted, so #app was taller than the
     visible area and the first scroll went into collapsing that chrome —
     carrying #view, and everything stuck to its top, up off the screen. The
     header was never unstuck; its container was moving.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSS = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

MOBILE_Q = "@media (max-width:820px){"
STICKY_SELECTORS = [".group-head", ".tbl th"]


def _mobile_block():
    i = CSS.index(MOBILE_Q)
    j, depth = i + len(MOBILE_Q), 1
    while depth:
        if CSS[j] == "{":
            depth += 1
        elif CSS[j] == "}":
            depth -= 1
        j += 1
    return CSS[i:j]


def test_the_narrow_screen_rules_do_not_unstick_the_header():
    block = _mobile_block()
    for sel in STICKY_SELECTORS:
        for m in re.finditer(re.escape(sel) + r"[^{}]*\{([^{}]*)\}", block):
            body = m.group(1)
            assert "position:" not in body.replace(" ", ""), (
                f"the mobile block changes position for '{sel}': {body!r}")
            assert not re.search(r"(?<!-)\btop\s*:", body), (
                f"the mobile block changes the sticky offset for '{sel}': {body!r}")


@pytest.mark.parametrize("sel,offset", [(".group-head", "top:0"), (".tbl th", "top:32px")])
def test_the_desktop_sticky_rules_are_still_there(sel, offset):
    """If these move, the test above is guarding nothing."""
    m = re.search(re.escape(sel) + r"\{([^{}]*)\}", CSS)
    assert m, f"{sel} has no rule at all"
    body = m.group(1).replace(" ", "")
    assert "position:sticky" in body, f"{sel} is no longer sticky"
    assert offset.replace(" ", "") in body, f"{sel} lost its {offset} offset"


def test_the_app_is_as_tall_as_the_visible_screen_not_the_retracted_one():
    m = re.search(r"#app\{([^{}]*)\}", CSS)
    assert m, "#app has no rule"
    body = m.group(1)
    assert "100dvh" in body, (
        "#app is sized in vh only — on a phone that is taller than the screen, "
        "and scrolling drags the sticky header out of view with the container")
    assert body.index("height:100vh") < body.index("height:100dvh"), \
        "the vh fallback must be declared before the dvh override"


def test_the_board_does_not_hand_its_scroll_to_the_page():
    """Scroll chaining is the other half of the same problem: reaching the end
    of the board passed the gesture to the document, which moves the chrome."""
    m = re.search(r"#view\{([^{}]*)\}", CSS)
    assert m and "overscroll-behavior-y:contain" in m.group(1).replace(" ", ""), \
        "#view still chains its scroll to the document"


# ── mobile: item selection is a desktop affordance ──────────────────────
def test_the_item_checkbox_is_hidden_on_a_narrow_screen():
    block = _mobile_block()
    assert re.search(r"\.item-check\s*\{[^{}]*display:\s*none", block), \
        "the per-item checkbox still takes width in front of every item name"


def test_the_selection_bar_cannot_appear_on_a_narrow_screen():
    """Belt and braces: the selection is also cleared at the breakpoint, but a
    rotate-and-resize sequence must not be able to strand the bar on screen
    when there is no longer a checkbox to untick."""
    block = _mobile_block()
    assert re.search(r"#sel-bar\s*\{[^{}]*display:\s*none", block), \
        "the bulk-action bar can still show on a phone"


def test_entering_mobile_clears_a_selection_made_while_wide():
    m = re.search(r"matchMedia\(MOBILE_Q\)\.addEventListener\('change',\s*\(\)=>\{(.*?)\}\);",
                  CSS, re.S)
    assert m, "the breakpoint listener is gone"
    assert "clearSelection()" in m.group(1), \
        "narrowing the window leaves rows marked with no way to unmark them"
