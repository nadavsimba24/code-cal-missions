"""Group 26 — creating an environment leaves you able to see it.

Reported from production: "היא נוצרה" and then nothing under ניהול מערכת →
סביבות. The environment was really there. POST /api/environments wrote the row
and no membership, and GET /api/environments shows anyone who is not a
workspace admin only the environments they belong to — so it belonged to
nobody, appeared to nobody, and could not even be granted to anyone, because
handing out access needs someone who can already manage it.

Boards have never had this problem: their creator is written in as the board's
admin at creation. These tests hold environments to the same rule.
"""
import pytest

from conftest import ADMIN_ID, MEMBER_ID


@pytest.fixture
def creator_may_create(client):
    """Let the plain 'member' role create environments, then put it back.

    MEMBER_ID is deliberately not a workspace admin — that is the whole point:
    a workspace admin sees every environment regardless and could never have
    noticed this.
    """
    before = client.get("/api/role-permissions").json()
    matrix = before.get("matrix") or {}
    was = bool((matrix.get("member") or {}).get("create_environment"))
    client.put("/api/role-permissions",
               json={"actor_id": ADMIN_ID, "role": "member",
                     "capability": "create_environment", "allowed": True})
    yield MEMBER_ID
    client.put("/api/role-permissions",
               json={"actor_id": ADMIN_ID, "role": "member",
                     "capability": "create_environment", "allowed": was})


def _create(client, uid, name):
    r = client.post("/api/environments", json={"actor_id": uid, "name": name})
    assert r.status_code == 200, r.text
    return r.json()


def _visible_to(client, uid):
    r = client.get(f"/api/environments?user_id={uid}")
    assert r.status_code == 200, r.text
    return {e["id"] for e in r.json()["environments"]}


def test_the_creator_can_see_what_they_created(client, creator_may_create):
    """The report, in one line."""
    uid = creator_may_create
    env = _create(client, uid, "סביבה של הבודק")
    try:
        assert env["id"] in _visible_to(client, uid)
    finally:
        client.delete(f"/api/environments/{env['id']}?actor_id={ADMIN_ID}")


def test_the_creator_is_its_manager(client, creator_may_create):
    uid = creator_may_create
    env = _create(client, uid, "סביבה בניהול הבודק")
    try:
        assert env["my_role"] == "manager"
        assert env["can_manage"] is True
        # and the listing agrees with what create said
        mine = next(e for e in client.get(f"/api/environments?user_id={uid}").json()["environments"]
                    if e["id"] == env["id"])
        assert mine["can_manage"] is True
    finally:
        client.delete(f"/api/environments/{env['id']}?actor_id={ADMIN_ID}")


def test_the_creator_can_hand_out_access_to_it(client, creator_may_create):
    """Without a manager, an environment cannot be shared with anyone — the
    endpoint that adds members is itself gated on managing it."""
    uid = creator_may_create
    env = _create(client, uid, "סביבה לשיתוף")
    try:
        r = client.get(f"/api/environments/{env['id']}/members?actor_id={uid}")
        assert r.status_code == 200, r.text
        members = r.json()["members"]
        assert [m["user_id"] for m in members] == [uid]
        assert members[0]["role"] == "manager"
    finally:
        client.delete(f"/api/environments/{env['id']}?actor_id={ADMIN_ID}")


def test_a_workspace_admin_still_sees_it(client, creator_may_create):
    """The membership row must not narrow anything that was already visible."""
    uid = creator_may_create
    env = _create(client, uid, "סביבה שהמנהל רואה")
    try:
        assert env["id"] in _visible_to(client, ADMIN_ID)
    finally:
        client.delete(f"/api/environments/{env['id']}?actor_id={ADMIN_ID}")


def test_an_admins_own_environment_still_reads_as_admin(client):
    """A workspace admin creating one is told the role they actually have
    there, not the one the new row grants."""
    env = _create(client, ADMIN_ID, "סביבה של מנהל המערכת")
    try:
        assert env["my_role"] == "admin"
        assert env["can_manage"] is True
    finally:
        client.delete(f"/api/environments/{env['id']}?actor_id={ADMIN_ID}")


def test_someone_without_the_capability_still_cannot_create(client):
    """The membership row is granted after the permission check, never instead."""
    r = client.post("/api/environments", json={"actor_id": MEMBER_ID, "name": "אסור"})
    assert r.status_code == 403, r.text
    assert "אסור" not in {e["name"] for e in
                          client.get(f"/api/environments?user_id={ADMIN_ID}").json()["environments"]}
