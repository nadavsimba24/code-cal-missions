"""The delete action in the system-admin users table, run under node.

The server half is tests/test_delete_user.py. This is the part a person meets:
an irreversible action has to be presented as one. It is not offered for the
account in hand, the dialog says what it takes with it instead of asking "are
you sure?", and it names the alternative — because for somebody who simply left
the organisation, deactivating is the right answer and deleting is not.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "delete_user_ui.mjs"


def test_the_users_table_can_delete_a_person_and_says_what_that_costs():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
