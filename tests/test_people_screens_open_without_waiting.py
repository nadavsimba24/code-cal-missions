"""The two people screens answer the click, not the network.

ניהול מערכת → משתמשים fetched the users and then the departments one after
the other and drew nothing until both were back, so the button looked dead for
two round trips on every opening — including every «ביטול» out of a profile,
which reopens it. In חברים והרשאות each role change and each removal waited on
a second request, the whole member list again, before the row moved.

The browser half is pinned by tests/frontend/people_screens_open_without_waiting.mjs;
the server half (the invitation mail sent after the response) by
tests/test_a_board_invitation_does_not_wait_for_the_mail.py.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_the_people_screens_draw_before_the_people_arrive():
    """Driven harness: tests/frontend/people_screens_open_without_waiting.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "people_screens_open_without_waiting.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
