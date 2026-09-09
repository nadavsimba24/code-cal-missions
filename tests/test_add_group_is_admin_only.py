"""רק מנהל לוח מוסיף קבוצה — והמסך לא מציע את מה שהשרת יסרב לו.

A group is structure, the same kind of decision as a column, which this board
already treats as the admin's. An editor fills the board in — items, values, who
is on what — and that is untouched; what shelves the board has is not theirs.

The server enforces it (tests/test_authz.py). This harness covers the screen's
half: the "+ הוסף קבוצה" button is rendered for a board admin only, addGroup
refuses on its own before sending anything (a role can be taken away while the
board sits open), and a refusal from the server is shown in its own words rather
than as a generic failure.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "add_group_is_admin_only.mjs"


def test_the_board_screen_offers_the_button_to_admins_only():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
