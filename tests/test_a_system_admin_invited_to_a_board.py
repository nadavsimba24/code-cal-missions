"""An invitation adds; it must never take away.

Reported as "מנהל מערכת לא יכול למחוק אוטומציה": the delete came back 403 on
one board, while the same person administered every other board in the system.

A system administrator is an admin of every board, including ones nobody ever
added them to — `_board_role` has always said so. It said so *after* reading
the BoardMember row, so the moment somebody invited the administrator to a
board as "חבר לוח", the explicit row answered "editor" and that board became
the single place in the system they could not manage: no rules to write, none
to delete, no board settings. Being invited to a board cost them the board.

The same shape repeats one level up, and that half is worse. `WorkspaceMember`
is the row nearly every permission reads through `_ws_role`, and the workspace
screen wrote whatever role it was handed: inviting a מנהל מערכת to the
workspace as "חבר" overwrote it with "member", `_board_role` then answered None
on EVERY board, and `User.role` went on saying admin — so the users screen
listed them as a system administrator while they could not manage a single
board anywhere. Both halves produce the same report, and both are pinned here.

The rule: the system role wins over the membership row, at either level, for
every lowered role — editor and viewer alike. An invitation is additive by
nature, and the one act that is MEANT to lower a system administrator is the
users screen, which `_sync_ws_role` carries through. That is pinned too.
"""
import itertools

import pytest

import main as cityos_main
from models import BoardMember, WorkspaceMember

_seq = itertools.count(1)


@pytest.fixture
def sysadmin(client, admin_id):
    """A second system administrator — User.role == 'admin', as the users screen makes one.

    Demoted and deactivated again on the way out, and the reason is not
    tidiness. `_purge_removed_demo_users` keeps a demo account alive only while
    it is the LAST administrator, and the suite's own משה (ADMIN_ID) is one of
    those accounts. A second admin left standing lifts that protection, so the
    next test that runs the purge deletes משה — and every test after it is
    refused with "המשתמש אינו רשום במערכת", which reads like the product broke
    and is this fixture forgetting to clean up.
    """
    n = next(_seq)
    uid = client.post("/api/users", json={"actor_id": admin_id, "name": f"מנהלת מערכת {n}",
                                          "email": f"sa.invite{n}@cityos.test",
                                          "role": "admin"}).json()["id"]
    try:
        yield uid
    finally:
        client.patch(f"/api/users/{uid}",
                     json={"actor_id": admin_id, "role": "member", "is_active": False})


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _rule(client, bid, admin_id):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": "created_set_priority",
                             "config": {"a_priority": "high"}, "name": "כלל"}).json()["id"]


# ── the board row ────────────────────────────────────────────────────────────

def test_a_system_admin_is_a_board_admin_without_being_a_member(client, admin_id, sysadmin):
    """The rule that already held, kept so the reordering cannot silently drop it."""
    bid = _board(client, admin_id, "לוח שלא הוזמנה אליו")
    with cityos_main.Session(cityos_main.engine) as db:
        assert db.query(BoardMember).filter(BoardMember.board_id == bid,
                                            BoardMember.user_id == sysadmin).first() is None
        assert cityos_main._board_role(db, bid, sysadmin) == "admin"


def test_being_invited_as_a_board_member_does_not_demote_a_system_admin(client, admin_id, sysadmin):
    bid = _board(client, admin_id, "לוח שהוזמנה אליו כחברה")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": sysadmin, "role": "editor"})
    with cityos_main.Session(cityos_main.engine) as db:
        b = db.query(cityos_main.Board).filter(cityos_main.Board.id == bid).first()
        assert cityos_main._board_role(db, bid, sysadmin) == "admin"
        assert cityos_main._can_manage_automations(db, b, sysadmin) is True


def test_being_invited_as_a_viewer_does_not_demote_one_either(client, admin_id, sysadmin):
    bid = _board(client, admin_id, "לוח שהוזמנה אליו כצופה")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": sysadmin, "role": "viewer"})
    with cityos_main.Session(cityos_main.engine) as db:
        assert cityos_main._board_role(db, bid, sysadmin) == "admin"


def test_a_system_admin_invited_as_a_member_can_delete_the_boards_automations(
        client, admin_id, sysadmin):
    """The report itself, end to end: the confirm dialog's DELETE must go through."""
    bid = _board(client, admin_id, "לוח עם אוטומציה למחיקה")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": sysadmin, "role": "editor"})
    aid = _rule(client, bid, admin_id)
    r = client.delete(f"/api/automations/{aid}?user_id={sysadmin}")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deleted"


def test_an_ordinary_member_is_still_refused(client, admin_id, member_id):
    """The membership row still decides for everybody who is not a system admin."""
    bid = _board(client, admin_id, "לוח עם חבר רגיל")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    aid = _rule(client, bid, admin_id)
    r = client.delete(f"/api/automations/{aid}?user_id={member_id}")
    assert r.status_code == 403, r.text
    with cityos_main.Session(cityos_main.engine) as db:
        assert cityos_main._board_role(db, bid, member_id) == "editor"


# ── the workspace row: the same rule one level up ────────────────────────────

def test_being_invited_to_the_workspace_as_a_member_does_not_demote_one(
        client, admin_id, sysadmin):
    """The second half of the report, and the one that took away every board."""
    bid = _board(client, admin_id, "לוח כלשהו")
    r = client.post("/api/workspace/members",
                    json={"actor_id": admin_id, "user_id": sysadmin, "role": "member"})
    assert r.status_code == 200, r.text
    with cityos_main.Session(cityos_main.engine) as db:
        assert cityos_main._ws_role(db, sysadmin) == "admin"
        assert cityos_main._board_role(db, bid, sysadmin) == "admin"


def test_the_members_list_does_not_show_a_system_admin_as_a_plain_member(
        client, admin_id, sysadmin):
    """The stored row is pinned too — the two screens disagreeing is how this hid."""
    client.post("/api/workspace/members",
                json={"actor_id": admin_id, "user_id": sysadmin, "role": "member"})
    with cityos_main.Session(cityos_main.engine) as db:
        row = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == sysadmin).first()
        assert row is not None and row.role == "admin"


def test_the_workspace_screen_cannot_lower_a_system_admin_either(client, admin_id, sysadmin):
    """PATCH is the same write by another route."""
    r = client.patch(f"/api/workspace/members/{sysadmin}",
                     json={"actor_id": admin_id, "role": "viewer"})
    assert r.status_code == 200, r.text
    with cityos_main.Session(cityos_main.engine) as db:
        row = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == sysadmin).first()
        assert row.role == "admin"
        assert cityos_main._ws_role(db, sysadmin) == "admin"


def test_an_ordinary_member_can_still_be_given_any_workspace_role(client, admin_id, guinea_id):
    """The pin is for system administrators only; everybody else is as before."""
    try:
        r = client.post("/api/workspace/members",
                        json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
        assert r.status_code == 200, r.text
        with cityos_main.Session(cityos_main.engine) as db:
            row = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == guinea_id).first()
            assert row.role == "viewer"
            assert cityos_main._ws_role(db, guinea_id) == "viewer"
    finally:
        client.post("/api/workspace/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "member"})


def test_a_demotion_in_the_users_screen_still_works(client, admin_id, sysadmin):
    """The way a system administrator IS lowered — and it must still lower them."""
    r = client.patch(f"/api/users/{sysadmin}", json={"actor_id": admin_id, "role": "member"})
    assert r.status_code == 200, r.text
    bid = _board(client, admin_id, "לוח אחרי ההורדה")
    with cityos_main.Session(cityos_main.engine) as db:
        assert cityos_main._ws_role(db, sysadmin) == "member"
        assert cityos_main._board_role(db, bid, sysadmin) is None
