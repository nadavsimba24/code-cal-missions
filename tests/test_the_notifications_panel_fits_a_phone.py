"""On a phone the notifications panel fits the screen instead of running off it.

Reported on 2026-11-23: on mobile the התראות panel was cut off on its right
side. The panel hangs off the bell with a 330px minimum width, and the bell
is not at the edge of the app bar — the avatar sits beyond it — so on a narrow
screen the panel ran past the right edge and the start of every Hebrew line
was clipped. Inside the phone breakpoint it is pinned to the viewport, under
the app bar, with a gutter on both sides. !important because the element
carries its anchoring as an inline style.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _phone_block():
    at = SRC.index("@media (max-width:820px){")
    depth = 0
    for k in range(SRC.index("{", at), len(SRC)):
        if SRC[k] == "{":
            depth += 1
        elif SRC[k] == "}":
            depth -= 1
            if not depth:
                return SRC[at:k + 1]


def test_on_a_phone_the_panel_is_pinned_inside_the_screen():
    block = _phone_block()
    rule = re.search(r"\.notif-pop\{([^}]*)\}", block)
    assert rule, "no phone rule for the notifications panel"
    css = rule.group(1)
    assert "position:fixed" in css
    # both sides held off the edge — logical, so it holds in RTL and LTR
    assert "inset-inline:8px!important" in css
    # the desktop minimum is what pushed it off the screen
    assert "min-width:0" in css and "max-width:none" in css


def test_the_list_scrolls_inside_the_screen_rather_than_past_it():
    assert re.search(r"\.notif-pop \.notif-list\{max-height:calc\(100dvh - var\(--header-h\)",
                     _phone_block())


def test_the_desktop_panel_is_unchanged():
    assert ".notif-pop{min-width:330px;max-width:360px;padding:0;overflow:hidden}" in SRC
    assert 'id="pop-notif" style="inset-inline-start:auto;inset-inline-end:0"' in SRC
