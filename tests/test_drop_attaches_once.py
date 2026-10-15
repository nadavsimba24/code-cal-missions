"""קובץ שנגרר לשיחה מצורף פעם אחת, לא פעמיים.

Two drop handlers deliberately cover the composer: Chat.onDrop on the composer
itself, which can turn an Outlook drag carrying no file bytes into an .eml, and
the #chat-panel listener in bindDnd, so a file can be dropped anywhere on the
panel instead of only on the composer strip. The composer is inside the panel,
so a drop on it ran both — and every file was uploaded twice. For an email the
two copies did not even match, since the panel uploads the raw file while the
composer names it first.

Measured in a real browser before the fix: one synthetic drop on the composer,
two calls to _upload, the same name twice. The harness runs the real onDrop and
counts, and also checks the panel-wide handler is still there — without it the
stopPropagation this pins would be guarding nothing.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "drop_attaches_once.mjs"


def test_a_dropped_file_is_attached_once():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
