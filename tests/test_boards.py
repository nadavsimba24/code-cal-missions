"""Group 4 — boards & permissions (create/owner visibility/delete)."""


def test_create_board_requires_admin(client, member_id):
    """Only a workspace admin may create a board — no user_id or a plain member → 403."""
    # no user_id → not a workspace admin
    assert client.post("/api/boards", json={"name": "nope"}).status_code == 403
    # explicit non-admin member
    r = client.post("/api/boards", json={"name": "nope", "user_id": member_id})
    assert r.status_code == 403


def test_admin_can_create_and_delete_board(client, admin_id):
    """A workspace admin can create a board and then delete it."""
    r = client.post("/api/boards", json={"name": "pytest board", "department_id": 1, "user_id": admin_id})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        assert client.get(f"/api/boards/{bid}?user_id={admin_id}").status_code == 200
    finally:
        r = client.delete(f"/api/boards/{bid}?user_id={admin_id}")
        assert r.status_code in (200, 204), r.text


def test_board_owners_present(client, admin_id):
    """Board detail returns a non-empty owners list, each with a name."""
    b = client.get(f"/api/boards/1?user_id={admin_id}").json()
    assert isinstance(b.get("owners"), list) and len(b["owners"]) >= 1
    assert all("name" in o for o in b["owners"])


def test_owners_visible_to_non_admin_member(client, member_id):
    """Owners are visible to a non-admin board member too (not just admins)."""
    b = client.get(f"/api/boards/1?user_id={member_id}").json()
    assert b.get("my_role") in ("editor", "viewer", "admin")  # a member of board 1
    assert isinstance(b.get("owners"), list) and len(b["owners"]) >= 1


def test_new_board_starts_table_only(client, admin_id):
    """A freshly created board exposes only the main table view (no kanban/dashboard/etc)."""
    r = client.post("/api/boards", json={"name": "views board", "department_id": 1, "user_id": admin_id})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        views = client.get(f"/api/boards/{bid}?user_id={admin_id}").json().get("views")
        assert views == ["table"], views
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_board_admin_can_set_column_widths(client, admin_id):
    """A board admin sets column widths (drag-to-resize); values persist and clamp to 60..600."""
    r = client.post("/api/boards", json={"name": "width board", "department_id": 1, "user_id": admin_id})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        # out-of-range values are clamped; non-numeric silently dropped
        r = client.patch(f"/api/boards/{bid}", json={
            "user_id": admin_id,
            "col_widths": {"item": 320, "status": 5000, "tags": 10, "bad": "x"},
        })
        assert r.status_code == 200, r.text
        cw = client.get(f"/api/boards/{bid}?user_id={admin_id}").json().get("col_widths", {})
        assert cw.get("item") == 320
        assert cw.get("status") == 600   # clamped down
        assert cw.get("tags") == 60      # clamped up
        assert "bad" not in cw
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_non_admin_cannot_set_column_widths(client, member_id):
    """A non-admin board member cannot change column widths → 403."""
    r = client.patch("/api/boards/1", json={"user_id": member_id, "col_widths": {"item": 300}})
    assert r.status_code == 403
