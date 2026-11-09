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
    grille went with it: a drawn face can smile instead."""
    assert "function robotIcon(cls)" in SRC
    assert SRC.count("fa-solid fa-robot") == 2, \
        "fa-robot belongs to the AI agents now, nowhere else"
    for frag in ('${robotIcon()}</button>',           # the header button
                 "item(robotIcon(),'אוטומציות'",      # the ⋯ menu entry
                 "robotIcon('ic-pri')"):              # the dialog heading
        assert frag in SRC, frag
