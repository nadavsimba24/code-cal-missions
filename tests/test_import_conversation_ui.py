"""How an imported message reads in the conversation.

It carries the name of whoever wrote it where it came from, says it was
imported, and offers no profile for an author who has no account here.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "imported_comment.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_an_imported_message_is_shown_as_one():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_import_report_accounts_for_the_conversation():
    """An import that silently halved a board's conversation would look exactly
    like a board that never had one."""
    for marker in ("הודעות בשיחות", "messages_dropped", "conversation_items_unmatched"):
        assert marker in SRC, f"the import report says nothing about {marker}"
