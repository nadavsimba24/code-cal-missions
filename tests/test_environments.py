"""Group 11 — environment-level permissions (environment manager role)."""


def _envs(client, uid):
    return client.get(f"/api/environments?user_id={uid}").json()["environments"]


def test_environment_manager_lifecycle(client, admin_id, guinea_id, member_id):
    """A system admin can appoint an environment manager, who can then manage that
    environment's members, rename it, and create boards in it — without being a
    system admin. A plain member of the environment cannot."""
    # admin creates a fresh environment
    env = client.post("/api/environments", json={"actor_id": admin_id, "name": "סביבת בדיקה"}).json()
    eid = env["id"]
    board_id = None
    try:
        # only a system admin may appoint a manager
        r = client.post(f"/api/environments/{eid}/members",
                        json={"actor_id": admin_id, "user_id": guinea_id, "role": "manager"})
        assert r.status_code == 200, r.text
        # a plain member (access only)
        client.post(f"/api/environments/{eid}/members",
                    json={"actor_id": admin_id, "user_id": member_id, "role": "member"})

        # the environment now shows up for the manager with the right role
        mine = next(e for e in _envs(client, guinea_id) if e["id"] == eid)
        assert mine["my_role"] == "manager" and mine["can_manage"] is True
        # and as access-only for the plain member
        theirs = next(e for e in _envs(client, member_id) if e["id"] == eid)
        assert theirs["my_role"] == "member" and theirs["can_manage"] is False

        # the manager can view/manage members
        r = client.get(f"/api/environments/{eid}/members?actor_id={guinea_id}")
        assert r.status_code == 200, r.text
        assert r.json()["can_set_manager"] is False   # only a sysadmin hands out the manager role
        # the manager can rename the environment
        r = client.patch(f"/api/environments/{eid}", json={"actor_id": guinea_id, "name": "שם מעודכן"})
        assert r.status_code == 200, r.text
        # the manager can create a board in this environment
        r = client.post("/api/boards", json={"name": "לוח של מנהל סביבה", "user_id": guinea_id,
                                             "environment_id": eid})
        assert r.status_code == 200, r.text
        board_id = r.json()["id"]

        # a plain environment member cannot manage it
        assert client.get(f"/api/environments/{eid}/members?actor_id={member_id}").status_code == 403
        assert client.patch(f"/api/environments/{eid}",
                            json={"actor_id": member_id, "name": "לא מורשה"}).status_code == 403

        # an environment manager cannot hand out the manager role (sysadmin-only)
        assert client.patch(f"/api/environments/{eid}/members/{member_id}",
                            json={"actor_id": guinea_id, "role": "manager"}).status_code == 403
        # and adding someone as "manager" via a non-sysadmin manager downgrades to member
        client.post(f"/api/environments/{eid}/members",
                    json={"actor_id": guinea_id, "user_id": member_id, "role": "manager"})
        row = next(m for m in client.get(f"/api/environments/{eid}/members?actor_id={admin_id}").json()["members"]
                   if m["user_id"] == member_id)
        assert row["role"] == "member"
    finally:
        if board_id:
            client.delete(f"/api/boards/{board_id}?user_id={admin_id}")
        client.delete(f"/api/environments/{eid}?actor_id={admin_id}")


def test_remove_member_blocked_while_on_a_board(client, admin_id, guinea_id):
    """A participant can be removed from an environment only if they belong to no
    board in it; otherwise the API refuses with the offending board name."""
    env = client.post("/api/environments", json={"actor_id": admin_id, "name": "סביבת הסרה"}).json()
    eid = env["id"]
    board_id = None
    try:
        client.post(f"/api/environments/{eid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "member"})
        board_id = client.post("/api/boards", json={"name": "לוח מקושר", "user_id": admin_id,
                                                   "environment_id": eid}).json()["id"]
        client.post(f"/api/boards/{board_id}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
        # blocked while on the board
        r = client.delete(f"/api/environments/{eid}/members/{guinea_id}?actor_id={admin_id}")
        assert r.status_code == 400, r.text
        assert "לוח מקושר" in r.json()["detail"]
        # remove from the board → now removal succeeds
        client.delete(f"/api/boards/{board_id}/members/{guinea_id}?actor_id={admin_id}")
        r = client.delete(f"/api/environments/{eid}/members/{guinea_id}?actor_id={admin_id}")
        assert r.status_code == 200, r.text
    finally:
        if board_id:
            client.delete(f"/api/boards/{board_id}?user_id={admin_id}")
        client.delete(f"/api/environments/{eid}?actor_id={admin_id}")


def test_delete_environment_rules(client, admin_id, guinea_id):
    """Deleting an environment (the sysadmin action exposed in ניהול מערכת → סביבות):
    system-admin only, never the primary workspace, and its boards survive — they
    move to the primary environment instead of being deleted with it."""
    env = client.post("/api/environments", json={"actor_id": admin_id, "name": "סביבה למחיקה"}).json()
    eid = env["id"]
    board_id = None
    try:
        board_id = client.post("/api/boards", json={"name": "לוח בסביבה שתימחק",
                                                    "user_id": admin_id, "environment_id": eid}).json()["id"]
        # an environment manager is still not allowed to delete it
        client.post(f"/api/environments/{eid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "manager"})
        assert client.delete(f"/api/environments/{eid}?actor_id={guinea_id}").status_code == 403

        # the primary workspace can never be deleted
        primary = next(e for e in _envs(client, admin_id) if e["is_primary"])
        assert client.delete(f"/api/environments/{primary['id']}?actor_id={admin_id}").status_code == 400

        # the sysadmin deletes it — the environment is gone, the board moved to primary
        assert client.delete(f"/api/environments/{eid}?actor_id={admin_id}").status_code == 200
        assert not any(e["id"] == eid for e in _envs(client, admin_id))
        board = next(b for b in client.get(f"/api/boards?user_id={admin_id}").json() if b["id"] == board_id)
        assert board["environment_id"] == primary["id"]
        eid = None
    finally:
        if board_id:
            client.delete(f"/api/boards/{board_id}?user_id={admin_id}")
        if eid:
            client.delete(f"/api/environments/{eid}?actor_id={admin_id}")


def test_non_member_has_no_environment_access(client, admin_id, guinea_id):
    """A user with no membership in an environment can neither see nor manage it."""
    env = client.post("/api/environments", json={"actor_id": admin_id, "name": "סביבה סגורה"}).json()
    eid = env["id"]
    try:
        assert not any(e["id"] == eid for e in _envs(client, guinea_id))
        assert client.get(f"/api/environments/{eid}/members?actor_id={guinea_id}").status_code == 403
    finally:
        client.delete(f"/api/environments/{eid}?actor_id={admin_id}")
