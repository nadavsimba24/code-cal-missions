"""Returning to a board she just left should not rebuild it from nothing.

Switching boards did the whole job every time: a request to the server, every
item, every cell — even going back to a board she had left seconds earlier. A
working day is mostly moving between the same two or three boards, so most of
that work was being redone for an answer that had not changed.

A board she has already seen is now shown from memory at once and then checked
against the server in the background. The dangerous half of that is not the
speed, it is the checking: a stamp that fails to notice a change leaves her
looking at a board that is quietly out of date, which is worse than a slow
one. The harness pins what the stamp notices, one kind of change at a time,
and that the cache stays bounded and evicts the board she looked at longest
ago. Run out of index.html under node.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "board_cache.mjs"


def test_a_board_she_has_seen_comes_back_without_being_rebuilt():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
