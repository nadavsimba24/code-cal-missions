"""Where the app opens.

The main URL opens the primary workspace — the one every user is in. The board
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


def test_the_members_screen_says_the_workspace_is_everyones():
    """A member list is the wrong screen for a workspace nobody is invited to.
    It says so, and it offers appointing managers instead of adding people who
    are already there."""
    assert "כל משתמשי המערכת חברים בסביבה הזו" in SRC
    assert "const everyone=!!d.everyone;" in SRC
    assert "${everyone?'':`<div class=\"mem-add\">" in SRC, \
        "the add control is still offered on a workspace everyone is in"


def test_the_screen_also_says_what_it_does_not_grant():
    """The sentence that keeps someone from reading "everybody is a member" as
    "everybody sees everything"."""
    for part in ("לוח פרטי נראה רק למי שהוזמן אליו", "ולוח ציבורי"):
        assert part in SRC, part
