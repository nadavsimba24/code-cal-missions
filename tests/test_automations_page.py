"""The automations page — the board's ⚡ button and its three tabs.

יצירה (templates + from scratch), ניהול (every rule, on or off) and
היסטוריית הפעלות (runs, skips, failures, retries). The harness runs the real
Automations object out of index.html.
"""
import pathlib
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


def test_the_header_button_is_hidden_on_a_phone_not_removed():
    """It shares the log button's class, which the phone rule already hides —
    and the ⋯ menu keeps its own entry, so the page stays reachable there."""
    assert '#boardhead .bh-log,#boardhead .bh-owner{display:none}' in SRC
    assert 'class="bh-log" id="bh-auto"' in SRC
    assert "'אוטומציות','Automations.open()'" in SRC
