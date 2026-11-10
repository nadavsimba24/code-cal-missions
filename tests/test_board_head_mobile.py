"""What the board header shows on a phone.

The log is not removed, it relocates: its header button is hidden and the ⋯
menu gains an entry.

The "משתתפים" button is the opposite case and is pinned here for it. It took
the place of the old בעלים / מנהל לוח chip, which the phone rule hid outright
because a label that names the board admins is not worth the width. A button
is: it is how anybody — a viewer included — sees who is on the board, so it
stays on a phone and drops its word instead of itself.
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


def test_the_log_button_leaves_the_header():
    block = _mobile_block()
    m = re.search(r"#boardhead \.bh-log\{([^{}]*)\}", block)
    assert m and "display:none" in m.group(1), \
        "the log button still takes space in the phone header"


def test_the_members_button_stays_on_a_phone():
    """It is the only way to see who is on the board, so it may not be hidden —
    what it gives up on a small screen is the word, not the control."""
    block = _mobile_block()
    assert not re.search(r"#boardhead \.bh-members\{[^{}]*display:none", block), \
        "the members button was hidden on a phone — nothing replaces it there"
    m = re.search(r"#boardhead \.bh-members \.bh-mem-lbl\{([^{}]*)\}", block)
    assert m and "display:none" in m.group(1), \
        "the phone header should drop the word 'משתתפים' and keep icon + count"


def test_the_old_owner_chip_is_gone():
    """Replaced, not hidden: a rule for a chip nobody renders is dead weight,
    and the request was to take the indicator off the header."""
    assert "bh-owner" not in CSS and "ownerChipHTML" not in CSS


def test_the_log_is_not_simply_gone():
    """Hiding the button without the menu entry would remove the board log from
    the phone entirely."""
    assert "'לוג הלוח','BoardLog.open()'" in CSS, \
        "the header button is hidden but nothing replaced it in the menu"


def test_the_desktop_header_is_untouched():
    for marker in ('class="bh-log"', 'membersChipHTML()'):
        assert marker in CSS, f"the desktop header lost {marker}"


def test_the_members_dialog_reads_on_a_phone():
    """Everybody opens it now, not only an admin on a laptop. A member row is a
    name plus two controls and the invitation is three fields — side by side in
    320px they crush the name, so both stack there."""
    block = _mobile_block()
    assert re.search(r"\.mem-row\{[^{}]*flex-wrap:wrap", block), \
        "a member row does not wrap on a phone"
    assert re.search(r"\.mem-add\{[^{}]*flex-direction:column", block), \
        "the invitation is still one flex line on a phone"
