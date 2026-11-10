"""הוספת קבוצה מראש הלוח — ולא רק מהתחתית שלו.

"+ הוסף קבוצה" sat at the very foot of the board, past every row of it: on a
board of any size the way to add a shelf was a scroll away from the board's own
actions, and the group it made appeared down there too, away from where the eye
was. The caret on "פריט חדש" is a second way in — it holds הוספת קבוצה, the
one thing the button beside it does not do — and a group made from there lands
at the TOP of the board.

Two halves. The screen's half is the harness: the button goes on making an item
on its own, the caret is hidden from anybody who cannot add a group, and the two
read as one control. The server's half is here: asking for position 0 does NOT
by itself make a group first — every other group goes on claiming the position
it already had — so the order is stated in full afterwards, the way a drag of
the groups states it. That second call is what this file holds down.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "add_group_from_the_toolbar.mjs"


def _board(client, admin_id, name="לוח הוספת קבוצה מלמעלה"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _groups(client, bid, admin_id):
    """In the order the board draws them — position first, then id, which is the
    tie-break the screen uses too (two groups can share a position after a
    reorder, and the board must not read differently from the test)."""
    gs = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["groups"]
    return sorted(gs, key=lambda g: (g.get("position") or 0, g["id"]))


def test_the_screen_offers_the_caret_and_what_hangs_off_it():
    """Driven harness: tests/frontend/add_group_from_the_toolbar.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_position_zero_alone_does_not_make_a_group_first(client, admin_id):
    """The reason the second call exists. Without it the new group ties on 0
    with the group that was first, and a tie is broken by id — which puts the
    new group second, one place below where it was asked for. If this ever
    starts passing with the group first, the server grew the shift itself and
    the reorder below became belt and braces."""
    bid = _board(client, admin_id)
    before = _groups(client, bid, admin_id)
    assert len(before) >= 2, "the seeded board needs at least two groups for a tie"
    made = client.post("/api/groups", json={"board_id": bid, "name": "ראשונה?",
                                            "position": 0, "user_id": admin_id}).json()
    assert made["position"] == 0
    assert [g["id"] for g in _groups(client, bid, admin_id)][0] != made["id"]


def test_stating_the_whole_order_puts_the_new_group_at_the_top(client, admin_id):
    """What addGroup(true) does, in the two calls it makes."""
    bid = _board(client, admin_id)
    was = [g["id"] for g in _groups(client, bid, admin_id)]
    made = client.post("/api/groups", json={"board_id": bid, "name": "קבוצה חדשה",
                                            "position": 0, "user_id": admin_id}).json()
    r = client.post("/api/groups/reorder", json={"order": [made["id"]] + was,
                                                 "user_id": admin_id})
    assert r.status_code == 200, r.text
    after = [g["id"] for g in _groups(client, bid, admin_id)]
    assert after[0] == made["id"], "the new group is not at the top of the board"
    assert after[1:] == was, "the groups that were there changed order among themselves"


def test_the_foot_of_the_board_still_appends(client, admin_id):
    """A plain addGroup() sends no position, and the server puts it last. The
    new way in must not have moved the old one."""
    bid = _board(client, admin_id)
    was = [g["id"] for g in _groups(client, bid, admin_id)]
    made = client.post("/api/groups", json={"board_id": bid, "name": "אחרונה",
                                            "user_id": admin_id}).json()
    assert [g["id"] for g in _groups(client, bid, admin_id)] == was + [made["id"]]


def test_an_editor_is_still_refused_a_group_at_the_top(client, admin_id, member_id):
    """The caret is hidden from an editor, and the hiding is not the rule — the
    server is. Asking for one at position 0 is refused like any other."""
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"user_id": member_id, "role": "editor", "actor_id": admin_id})
    r = client.post("/api/groups", json={"board_id": bid, "name": "לא אמורה להיווצר",
                                         "position": 0, "user_id": member_id})
    assert r.status_code == 403, r.text
