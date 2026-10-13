"""A tag has an end: after a board member is picked, the rest of the line is the message.

A name holds spaces, so the "@…" autocomplete query had to allow them — and a
picked tag was therefore still read as an open query to the end of the line.
Every further word reopened the menu on the finished tag, its "no matching board
members" note sat over the composer, and Enter was taken by the menu (picking
the same person again) instead of inserting a newline. Pressing Enter *first*
was the only way to get a message typed, because a query cannot cross a newline
— which is exactly how it was reported.

Runs the real mentionCtx, mentionSettled, onType, _openMention, pickMention and
keydown out of index.html under node, the same way
tests/test_chat_date_year.py does; the harness names the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "mention_finished.mjs"


def test_a_picked_tag_does_not_keep_the_autocomplete_open():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
