"""The browser offers the new board roles, and offers for tagging only people
who can see the item.

The server is the rule (test_only_a_person_who_can_see_the_item_is_tagged.py):
an @mention or a people-column tag of an assigned_only member who is not on the
item is dropped. A picker that still offers them produces a tag that vanishes
on save with nothing to say why — so the pickers must agree with the server.
That is pinned by tests/frontend/only_who_can_see_the_item_is_offered.mjs,
which runs boardPeople() out of index.html.

What a harness cannot reach is asserted on the source: that the chat's @-menu
and the people cell actually hand boardPeople the item they are for (without
it, the narrowing never runs), and that the members dialog offers the two new
roles both when inviting and when changing somebody's role — a role the dialog
cannot pick is a role nobody can be given.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "only_who_can_see_the_item_is_offered.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
NEW_ROLES = ("assigned_editor", "assigned_only")


def test_the_pickers_offer_only_people_who_can_see_the_item():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def _members_roles():
    m = re.search(r"^  ROLES\s*:\s*\[([^\]]*)\]", SRC, re.M)
    assert m, "Members.ROLES is gone — the role picker has no list to draw"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def test_the_role_picker_lists_both_new_roles():
    """Both pickers in the members dialog — the invitation and a member's row —
    are the one two-line menu (roleBtnHTML → roleMenu → roleChoose), drawn
    from Members.ROLES."""
    roles = _members_roles()
    for role in NEW_ROLES:
        assert role in roles, f"the role menu cannot pick {role}: {roles}"
    menu = re.search(r"^  roleMenu\(.*?^  \}", SRC, re.M | re.S)
    assert menu and "this.ROLES" in menu.group(0), "the role menu no longer draws Members.ROLES"


def test_the_invitation_uses_the_role_picker():
    assert re.search(r"roleBtnHTML\([^\n]*Members\.pickInviteRole", SRC), \
        "the invitation has no role picker, so a new member cannot be invited into a new role"


def test_changing_a_members_role_uses_the_role_picker():
    assert re.search(r"roleBtnHTML\([^\n]*Members\.setRole\(", SRC), \
        "a member's row has no role picker, so nobody can be moved to a new role"


def test_both_new_roles_have_a_hebrew_name():
    m = re.search(r"^const BROLE_HE\s*=\s*\{.*?\};", SRC, re.M | re.S)
    assert m, "BROLE_HE is gone"
    for role in NEW_ROLES:
        assert re.search(role + r"\s*:\s*'[^']*[֐-׿]", m.group(0)), \
            f"{role} would be shown to the user by its code name"


def test_the_chat_mention_menu_hands_the_picker_its_item():
    """Without the item the narrowing never runs, and the @-menu offers
    everybody on the board again."""
    assert re.search(r"boardPeople\([^;\n]*\{\s*item\s*:\s*this\.task", SRC), \
        "the chat's @-menu no longer tells boardPeople which item it is for"


def test_a_people_cell_hands_the_picker_its_item_and_column():
    """The column matters as much as the item: the permission column is the
    one place an assigned_only member must still be offered."""
    assert re.search(r"boardPeople\([^;\n]*\{\s*item\s*:\s*t\s*,\s*col\s*:\s*colId", SRC), \
        "a board people column no longer narrows its picker to the item"
    assert re.search(r"boardPeople\([^;\n]*\{\s*item\s*:\s*t\s*,\s*col\s*:\s*'assignees'", SRC), \
        "the built-in assignee picker no longer narrows to the item"
