"""The automations page — the board's ⚡ button and its three tabs.

יצירה (templates + from scratch), ניהול (every rule, on or off) and
היסטוריית הפעלות (runs, skips, failures, retries). The harness runs the real
Automations object out of index.html.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "automations_page.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_three_tabs_and_the_way_into_them():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_header_button_stays_in_the_header_on_a_phone():
    """It wears the log button's styling and takes a different decision about
    the phone. The log leaves the header there and lives in the ⋯ menu instead;
    automations is in both places on every screen, which is what was asked for
    after it went missing from the header in QA. The rule that spares it has to
    come after the one that hides .bh-log — same specificity, later wins."""
    assert 'class="bh-log bh-auto" id="bh-auto"' in SRC
    hide = re.search(r"#boardhead [^{}\n]*\.bh-log[^{}\n]*\{[^{}]*display:none", SRC)
    assert hide, "nothing hides the log button on a phone any more"
    keep = SRC.find('#boardhead .bh-auto{display:inline-grid}')
    assert keep > 0, "the automations button is hidden on a phone with the log"
    assert hide.start() < keep, \
        "the rule that spares it has to come after the one that hides .bh-log"
    assert "'אוטומציות','Automations.open()'" in SRC


def test_the_automations_mark_is_drawn_here_not_fetched():
    """Font Awesome comes from a CDN, and where the CDN is unreachable the
    button renders empty — "the icon did not come up" in QA, with the markup
    present all along. The mark is an inline svg now, and fa-robot's toothy
    grille went with it: a drawn face can smile instead.

    There is one robot in the product, not two. fa-robot survived for a while
    on the page-agent bubble and the AI agent cards, which meant two faces
    that differed by a tooth — nobody could name it and everybody saw it."""
    assert "function robotIcon(cls)" in SRC
    assert SRC.count("fa-solid fa-robot") == 0, \
        "the drawn face is the only robot; fa-robot belongs nowhere now"
    for frag in ('${robotIcon()}</button>',           # the header button
                 "item(robotIcon(),'אוטומציות'",      # the ⋯ menu entry
                 "robotIcon('ic-pri')"):              # the dialog heading
        assert frag in SRC, frag


def test_the_robot_is_filled_like_the_icons_around_it():
    """It was an outline among Font Awesome's solid set — in the ⋯ menu, next
    to a solid lock and a solid bell, a line drawing read as a sticker someone
    had dropped in. It is a silhouette now, and the eyes and smile are holes
    punched through it by evenodd rather than white shapes painted on: a hole
    shows what is behind it, so the same face is right on a white menu, on the
    dark theme and on the coloured agent bubble with no second colour to set."""
    mark = SRC[SRC.index("function robotIcon(cls)"):]
    mark = mark[:mark.index("\n}")]
    assert 'fill="currentColor" stroke="none"' in mark, "the mark is filled, not stroked"
    assert 'stroke-width' not in mark, "an outline again"
    assert 'fill-rule="evenodd"' in mark, "the face has to be holes, not paint"
    assert '#fff' not in mark and 'white' not in mark, \
        "a painted-white eye is wrong everywhere the background is not white"


def test_there_is_only_one_robot_drawing_in_the_source():
    """The page-agent bubble used to carry its own copy of the svg in the
    markup. Two copies of a drawing drift, and a robot that differs from the
    one in the ⋯ menu by a tooth is the kind of thing nobody can name and
    everybody sees — so the bubble is filled from robotIcon() at boot."""
    assert SRC.count('<circle cx="12"') == 1, "a second copy of the face"
    assert 'id="fab-robot"' in SRC
    assert "fabRobot.innerHTML=robotIcon()" in SRC
