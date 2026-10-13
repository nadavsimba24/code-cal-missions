"""The notification bell has to move when the notification arrives.

A like notifies its comment's author (tests/test_comment_like_notifies.py), and
this is the other half: the author's bell learning about it from the event
stream instead of waiting out the reconcile interval. It did not — the bump
called an object that does not exist, inside a try/catch that hid it.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "notif_bump.mjs"


def test_an_event_from_somebody_else_refreshes_the_bell():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
