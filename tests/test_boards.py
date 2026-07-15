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
