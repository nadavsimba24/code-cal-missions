"""The users table must NOT offer permanent deletion.

The capability exists and is covered by tests/test_delete_user.py — system
admin only, every reference accounted for, the purge itself logged. It was
built with a button in the system-admin screen and used once, for an account
that should never have existed here; the button was then removed on purpose.
Erasing a person is irreversible, and one click away from a rename is the wrong
place for it, so it is reached deliberately rather than from a menu.

This runs the guard under node: it fails if the affordance comes back.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "delete_user_ui.mjs"


def test_the_users_table_does_not_offer_permanent_deletion():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
