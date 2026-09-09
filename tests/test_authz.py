"""Group 14 — board-mutation authorization (IDOR fixes on groups + task move)."""


def test_non_member_cannot_mutate_a_board(client, admin_id, guinea_id):
    """A user who is not a member of a board cannot create/rename/delete its groups
    or move its tasks; the board admin can. Closes the IDOR on board mutations."""
    b = client.post("/api/boards", json={"name": "לוח הרשאות", "user_id": admin_id}).json()
    bid = b["id"]
    try:
        # guinea is not a member of this fresh board → blocked from creating a group
        assert client.post("/api/groups", json={"board_id": bid, "name": "x", "actor_id": guinea_id}).status_code == 403
        # the board admin can
        r = client.post("/api/groups", json={"board_id": bid, "name": "ok", "actor_id": admin_id})
        assert r.status_code == 200, r.text
        gid = r.json()["id"]
        # non-member cannot rename or delete the group
        assert client.patch(f"/api/groups/{gid}", json={"name": "y", "actor_id": guinea_id}).status_code == 403
        assert client.delete(f"/api/groups/{gid}?actor_id={guinea_id}").status_code == 403
        # a task on the board — non-member cannot move it, admin can
        t = client.post("/api/tasks", json={"title": "t", "board_id": bid, "group_id": gid, "user_id": admin_id}).json()
        assert client.post(f"/api/tasks/{t['id']}/move", json={"position": 1, "actor_id": guinea_id}).status_code == 403
        assert client.post(f"/api/tasks/{t['id']}/move", json={"position": 1, "actor_id": admin_id}).status_code == 200
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_board_member_can_mutate(client, admin_id, guinea_id):
    """An invited editor of a board can mutate it (positive path).

    Filling the board in is the editor's: items, values, who is on what."""
    b = client.post("/api/boards", json={"name": "לוח חברים", "user_id": admin_id}).json()
    bid = b["id"]
    gid = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["groups"][0]["id"]
    try:
        client.post(f"/api/boards/{bid}/members", json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
        r = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                            "title": "פריט של עורך", "actor_id": guinea_id})
        assert r.status_code == 200, r.text
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_only_a_board_admin_adds_a_group(client, admin_id, guinea_id, member_id):
    """A group is structure, like a column — the board's admin decides it.

    An editor fills a board in; what shelves it has is not theirs to change. The
    refusal says which permission is missing, because "אין לך הרשאה לשנות לוח
    זה" is a lie to an editor: they change the board all day."""
    b = client.post("/api/boards", json={"name": "לוח מבנה", "user_id": admin_id}).json()
    bid = b["id"]
    try:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": member_id, "role": "viewer"})

        r = client.post("/api/groups", json={"board_id": bid, "name": "של עורך",
                                             "actor_id": guinea_id})
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == "רק מנהל הלוח יכול להוסיף קבוצות"

        assert client.post("/api/groups", json={"board_id": bid, "name": "של צופה",
                                                "actor_id": member_id}).status_code == 403

        # and the board's admin still adds one
        r = client.post("/api/groups", json={"board_id": bid, "name": "של מנהל",
                                             "actor_id": admin_id})
        assert r.status_code == 200, r.text
        names = [g["name"] for g in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["groups"]]
        assert names.count("של מנהל") == 1 and "של עורך" not in names
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_an_editor_who_cannot_add_a_group_can_still_work_the_board(client, admin_id, guinea_id):
    """The restriction is on structure alone — nothing else moved with it."""
    b = client.post("/api/boards", json={"name": "לוח עבודה", "user_id": admin_id}).json()
    bid = b["id"]
    gid = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["groups"][0]["id"]
    try:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
        t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                            "title": "פריט", "actor_id": guinea_id})
        assert t.status_code == 200, t.text
        tid = t.json()["id"]
        assert client.patch(f"/api/tasks/{tid}",
                            json={"status": "done", "actor_id": guinea_id}).status_code == 200
        assert client.post(f"/api/tasks/{tid}/move",
                           json={"group_id": gid, "actor_id": guinea_id}).status_code == 200
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")
