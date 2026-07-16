"""Group 3 — task lifecycle: create → read → update → comment → move → delete."""


def _board_group(client, board_id=1):
    b = client.get(f"/api/boards/{board_id}?user_id=1").json()
    gid = b["groups"][0]["id"] if b.get("groups") else None
    return gid


def test_task_lifecycle(client):
    """Full task flow: create -> appears on board -> update -> comment -> move -> delete."""
    gid = _board_group(client)

    # create
    r = client.post("/api/tasks", json={"title": "pytest task", "board_id": 1, "group_id": gid})
    assert r.status_code == 200, r.text
    tid = r.json()["id"]

    try:
        # appears in the board
        board = client.get("/api/boards/1?user_id=1").json()
        ids = [t["id"] for t in board["tasks"]]
        assert tid in ids

        # update
        r = client.patch(f"/api/tasks/{tid}", json={"title": "pytest task updated"})
        assert r.status_code in (200, 204), r.text

        # comment (acting user 1 is a board admin → allowed)
        r = client.post(f"/api/tasks/{tid}/comments", json={"content": "hi", "user_id": 1})
        assert r.status_code in (200, 201), r.text
        comments = client.get(f"/api/tasks/{tid}/comments").json()["comments"]
        assert any("hi" in (c.get("content") or "") for c in comments)

        # move
        r = client.post(f"/api/tasks/{tid}/move", json={"group_id": gid, "position": 0})
        assert r.status_code in (200, 204), r.text

        # activity log reads
        assert client.get(f"/api/tasks/{tid}/activity").status_code == 200
    finally:
        # delete (cleanup so the shared DB stays tidy)
        r = client.delete(f"/api/tasks/{tid}")
        assert r.status_code in (200, 204), r.text


def test_status_change_auto_moves_to_matching_group(client):
    """Changing a top-level item's status moves it to the group for that status:
    exact task_status match first, else the same coarse stage (todo/active/done)."""
    b = client.get("/api/boards/1?user_id=1").json()
    stage = {"backlog": "todo", "todo": "todo", "in_progress": "active",
             "review": "active", "on_hold": "active", "done": "done", "cancelled": "done"}
    by_status = {g["task_status"]: g["id"] for g in b["groups"]}
    gid = b["groups"][0]["id"]
    r = client.post("/api/tasks", json={"title": "move-me", "board_id": 1, "group_id": gid})
    tid = r.json()["id"]
    try:
        for status in ("done", "in_progress", "review", "cancelled", "todo"):
            r = client.patch(f"/api/tasks/{tid}", json={"status": status, "user_id": 1})
            assert r.status_code == 200, r.text
            board = client.get("/api/boards/1?user_id=1").json()
            task = next(t for t in board["tasks"] if t["id"] == tid)
            landed = board["groups"][[g["id"] for g in board["groups"]].index(task["group_id"])]
            # the group it landed in must share the status' stage
            assert stage.get(landed["task_status"]) == stage.get(status), \
                f"status {status} landed in {landed['task_status']}"
    finally:
        client.delete(f"/api/tasks/{tid}")
