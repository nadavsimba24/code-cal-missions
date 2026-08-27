"""What the board header shows on a phone.

The log is not removed, it relocates: its header button is hidden and the ⋯
menu gains an entry. The owner chip is removed outright — and on a phone that
is its only appearance, since boardMenu disables the members screen for anyone
who is not a board admin.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "board_menu_mobile.mjs"
CSS = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _mobile_block():
    q = "@media (max-width:820px){"
    i = CSS.index(q)
    j, depth = i + len(q), 1
    while depth:
        if CSS[j] == "{":
            depth += 1
        elif CSS[j] == "}":
            depth -= 1
        j += 1
    return CSS[i:j]


def test_the_log_moves_into_the_board_menu():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_log_button_and_the_owner_leave_the_header():
    block = _mobile_block()
    m = re.search(r"#boardhead \.bh-log,#boardhead \.bh-owner\{([^{}]*)\}", block)
    assert m and "display:none" in m.group(1), \
        "the log button and/or the owner chip still take space in the phone header"


def test_the_log_is_not_simply_gone():
    """Hiding the button without the menu entry would remove the board log from
    the phone entirely."""
    assert "'לוג הלוח','BoardLog.open()'" in CSS, \
        "the header button is hidden but nothing replaced it in the menu"


def test_the_desktop_header_is_untouched():
    for marker in ('class="bh-log"', 'ownerChipHTML()'):
        assert marker in CSS, f"the desktop header lost {marker}"
