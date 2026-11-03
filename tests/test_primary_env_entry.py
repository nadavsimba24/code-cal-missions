"""Where the app opens.

The main URL opens the primary workspace — the one new boards land in. The board
you were on is restored only if it lives there; a link that names a board
somewhere else wins, and takes its workspace with it, so the switcher never
names one place while the board on screen belongs to another.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "primary_env_entry.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_main_url_opens_the_primary_workspace():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_members_screen_is_the_ordinary_one():
    """The primary workspace used to get a screen of its own — every account in
    the system listed, and no way to add anyone, because everybody was in it by
    definition. That is precisely what handed the invite picker of every board
    inside it the whole directory, so the workspace is now managed like the
    others and the screen is the ordinary one."""
    assert "כל משתמשי המערכת חברים בסביבה הזו" not in SRC
    assert "const everyone=" not in SRC
    assert "d.everyone" not in SRC and "membersData.everyone" not in SRC, \
        "the screen still branches on a flag the server no longer sends"


def test_it_says_who_the_members_are_and_what_being_one_is_for():
    assert "רק חברי הסביבה רואים אותה ואת לוחותיה, ורק אותם אפשר להזמין ללוחות שבתוכה" in SRC


def test_the_board_invite_picker_says_what_it_is_a_list_of():
    """An empty picker is otherwise unreadable: it looks like a bug rather than
    a workspace nobody has been added to yet."""
    assert "הרשימה היא חברי הסביבה שהלוח שייך אליה" in SRC
    assert "— אין חברי סביבה שאפשר להוסיף —" in SRC
