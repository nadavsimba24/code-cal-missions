"""The board header's "משתתפים" button, and what the server lets it do.

The header used to carry a בעלים / מנהל לוח chip: a label naming the board's
admins, which told a viewer who to ask and nothing else, while the one screen
that lists everybody was behind a menu entry disabled for anybody but an admin.
It is now a button with a count, and everyone on the board may press it.

That opens a door, so the rule this file pins is that the door is a window for
most people:

  * the member list answers anyone who is on the board, so a viewer can read it
  * it answers nobody who is not — the button is on their screen because they
    are on the board, never because they asked
  * it reports `can_manage`, which is what the dialog draws its controls off
  * `can_manage` is advice about drawing, never a grant: every write re-asks
    _is_board_admin, so an editor who issues the request by hand is refused
  * `available` — who could still be invited — goes only to someone who could
    issue the invitation; it is a directory of colleagues otherwise

tests/frontend/board_participants.mjs pins the other half: what the dialog
draws in each mode.
"""
import pathlib
import shutil
import subprocess

import pytest

from conftest import ADMIN_ID, MEMBER_ID, join_primary_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
HARNESS = ROOT / "tests" / "frontend" / "board_participants.mjs"


def _mk_board(client, name="לוח משתתפים"):
    return client.post("/api/boards", json={"name": name, "actor_id": ADMIN_ID}).json()["id"]


def _mk_user(client, name, email):
    r = client.post("/api/users", json={"name": name, "email": email, "actor_id": ADMIN_ID})
    uid = r.json()["id"]
    join_primary_env(client, uid)
    return uid


# ── who may read the list ────────────────────────────────────────────────


def test_a_board_viewer_may_see_who_is_on_the_board(client):
    """The button is on their header, so the list has to answer them."""
    bid = _mk_board(client)
    try:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": ADMIN_ID, "user_id": MEMBER_ID, "role": "viewer"})
        r = client.get(f"/api/boards/{bid}/members", headers={"X-CityOS-User": str(MEMBER_ID)})
        assert r.status_code == 200, r.text
        d = r.json()
        assert {m["user_id"] for m in d["members"]} == {ADMIN_ID, MEMBER_ID}
        # every row says what the person is, which is what the dialog shows
        assert all(m["role"] in ("admin", "editor", "viewer") for m in d["members"])
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={ADMIN_ID}")


def test_a_stranger_to_the_board_is_refused(client):
    """Membership is what makes the list readable — not having guessed the id."""
    bid = _mk_board(client, "לוח סגור")
    outsider = _mk_user(client, "זר לבדיקה", "stranger.participants@cityos.test")
    try:
        client.patch(f"/api/boards/{bid}", json={"actor_id": ADMIN_ID, "visibility": "private"})
        r = client.get(f"/api/boards/{bid}/members", headers={"X-CityOS-User": str(outsider)})
        assert r.status_code == 403, r.text
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={ADMIN_ID}")


def test_an_unknown_board_is_a_404_not_an_empty_list(client):
    r = client.get("/api/boards/99887766/members", headers={"X-CityOS-User": str(ADMIN_ID)})
    assert r.status_code == 404, r.text


# ── can_manage: what the dialog draws, and what the server actually allows ──


def test_can_manage_tells_the_dialog_which_mode_to_open_in(client):
    bid = _mk_board(client)
    try:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": ADMIN_ID, "user_id": MEMBER_ID, "role": "editor"})
        admin = client.get(f"/api/boards/{bid}/members",
                           headers={"X-CityOS-User": str(ADMIN_ID)}).json()
        editor = client.get(f"/api/boards/{bid}/members",
                            headers={"X-CityOS-User": str(MEMBER_ID)}).json()
        assert admin["can_manage"] is True
        assert editor["can_manage"] is False
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={ADMIN_ID}")


def test_who_may_still_be_invited_is_only_told_to_whoever_could_invite(client):
    """`available` is the environment's directory. An editor cannot act on it and
    did not ask for it — the dialog draws no invitation for them at all."""
    bid = _mk_board(client)
    try:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": ADMIN_ID, "user_id": MEMBER_ID, "role": "editor"})
        admin = client.get(f"/api/boards/{bid}/members",
                           headers={"X-CityOS-User": str(ADMIN_ID)}).json()
        editor = client.get(f"/api/boards/{bid}/members",
                            headers={"X-CityOS-User": str(MEMBER_ID)}).json()
        assert admin["available"], "an admin has somebody left to invite"
        assert editor["available"] == []
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={ADMIN_ID}")


def test_reading_the_list_grants_nothing(client):
    """The whole point of showing the button to everybody. An editor who can see
    the dialog still cannot change a role, remove anybody, or invite — however
    the request is made, and whatever the browser chose to draw."""
    bid = _mk_board(client)
    guest = _mk_user(client, "מועמד לבדיקה", "candidate.participants@cityos.test")
    try:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": ADMIN_ID, "user_id": MEMBER_ID, "role": "editor"})
        as_editor = {"X-CityOS-User": str(MEMBER_ID)}

        r = client.post(f"/api/boards/{bid}/members", headers=as_editor,
                        json={"user_id": guest, "role": "editor"})
        assert r.status_code == 403, r.text

        r = client.patch(f"/api/boards/{bid}/members/{MEMBER_ID}", headers=as_editor,
                         json={"role": "admin"})
        assert r.status_code == 403, r.text

        r = client.delete(f"/api/boards/{bid}/members/{ADMIN_ID}", headers=as_editor)
        assert r.status_code == 403, r.text

        # …and none of it happened
        after = client.get(f"/api/boards/{bid}/members",
                           headers={"X-CityOS-User": str(ADMIN_ID)}).json()
        roles = {m["user_id"]: m["role"] for m in after["members"]}
        assert roles == {ADMIN_ID: "admin", MEMBER_ID: "editor"}
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={ADMIN_ID}")


def test_a_passed_user_id_does_not_choose_who_is_asking(client):
    """Identity comes from the transport. ?user_id= on this route would be a way
    for an editor to be told what an admin is told."""
    bid = _mk_board(client)
    try:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": ADMIN_ID, "user_id": MEMBER_ID, "role": "editor"})
        r = client.get(f"/api/boards/{bid}/members?user_id={ADMIN_ID}&actor_id={ADMIN_ID}",
                       headers={"X-CityOS-User": str(MEMBER_ID)})
        assert r.status_code == 200, r.text
        assert r.json()["can_manage"] is False
        assert r.json()["available"] == []
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={ADMIN_ID}")


# ── the header itself ────────────────────────────────────────────────────


def test_the_header_carries_a_participants_button_and_not_the_old_chip():
    assert "membersChipHTML()" in SRC, "the board header lost the משתתפים button"
    assert 'class="bh-members"' in SRC
    assert "ownerChipHTML" not in SRC and "bh-owner" not in SRC, \
        "the בעלים / מנהל לוח indicator was supposed to be removed, not hidden"


def test_the_menu_entry_is_open_to_everyone_too():
    """It used to be disabled for anyone who was not a board admin, which is why
    the old chip was the only thing a viewer could read. The dialog handles
    read-only itself now, so the entry no longer gates on the role."""
    assert "'משתתפים והרשאות','Members.open()',true" in SRC


def test_the_count_is_the_boards_own_member_list():
    """So the number on the button and the names in every people picker on the
    board cannot disagree — they are the same list."""
    assert "function boardMemberCount()" in SRC
    assert "st.board&&st.board.members" in SRC


def test_the_button_and_the_dialog_render_as_specified():
    """Runs the real membersChipHTML and the real Members object: the count on
    the button, and the dialog's two modes — manage and read-only."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
