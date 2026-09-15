"""The organisational automations page and the board's bulk actions, on screen.

The rules the harness checks are the ones the spec is specific about: the count
and the warnings before anything happens, a separate result per automation
after, no bulk delete, and an organisation-wide stop that asks for a reason and
a second confirmation and says it will not expire by itself.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "automations_bulk.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_page_and_the_bulk_bar_behave():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_organisational_view_is_a_tab_of_the_system_admin_screen():
    assert "data-tab=\"autos\"" in SRC
    assert "SysAdmin.go('autos')" in SRC
    assert "this.renderAutos();" in SRC


def test_nothing_in_the_bulk_bar_deletes():
    """Left out of the MVP on purpose — see the server's AUTOMATION_BULK_ACTIONS."""
    bar = SRC[SRC.index("bulkBarHTML(){"):SRC.index("bulkOwner(e){")]
    for word in ("del(", "מחק", "delete"):
        assert word not in bar, f"the bulk bar offers {word}"
