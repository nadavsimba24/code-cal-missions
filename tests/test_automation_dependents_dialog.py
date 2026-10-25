"""דיאלוג המחיקה מראה את התלויות — driven harness.

The server works out who depends on what; this is about the screen asking
before the deletion rather than the engine explaining after it. Checked in
tests/frontend/automation_dependents.mjs.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_the_delete_dialog_shows_what_depends_on_it():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_dependents.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
