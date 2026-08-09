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
    """An invited editor of a board can mutate it (positive path)."""
    b = client.post("/api/boards", json={"name": "לוח חברים", "user_id": admin_id}).json()
    bid = b["id"]
    try:
        client.post(f"/api/boards/{bid}/members", json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
        r = client.post("/api/groups", json={"board_id": bid, "name": "מקבוצת עורך", "actor_id": guinea_id})
        assert r.status_code == 200, r.text
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")
