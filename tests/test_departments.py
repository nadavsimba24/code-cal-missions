"""Group 9 — organizational-unit (department) management for system admins."""


def _list(client):
    return client.get("/api/departments").json()


def test_departments_list_shape(client):
    """/api/departments exposes the fields the admin panel needs, incl. usage counts."""
    depts = _list(client)
    assert depts, "expected at least one seeded department"
    for key in ("id", "name", "code", "color", "user_count", "board_count"):
        assert key in depts[0], f"department missing '{key}'"


def test_non_admin_cannot_create_department(client, member_id):
    """A non-admin cannot create an organizational unit → 403."""
    r = client.post("/api/departments", json={"actor_id": member_id, "name": "יחידה אסורה"})
    assert r.status_code == 403, r.text


def test_admin_department_crud_roundtrip(client, admin_id):
    """Admin can create, rename/recolor, and delete an organizational unit."""
    import uuid as _uuid
    name = f"יחידת בדיקה {_uuid.uuid4().hex[:6]}"
    r = client.post("/api/departments", json={"actor_id": admin_id, "name": name, "code": "QA", "color": "#123456"})
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    try:
        assert any(d["id"] == did for d in _list(client))
        r = client.patch(f"/api/departments/{did}", json={"actor_id": admin_id, "name": name + " (מעודכן)", "color": "#654321"})
        assert r.status_code == 200, r.text
        updated = next(d for d in _list(client) if d["id"] == did)
        assert updated["name"].endswith("(מעודכן)") and updated["color"] == "#654321"
    finally:
        d = client.delete(f"/api/departments/{did}?actor_id={admin_id}")
        assert d.status_code == 200, d.text
    assert not any(d["id"] == did for d in _list(client))


def test_duplicate_department_name_rejected(client, admin_id):
    """Creating a unit whose name collides (case-insensitive) → 409."""
    existing = _list(client)[0]["name"]
    r = client.post("/api/departments", json={"actor_id": admin_id, "name": existing})
    assert r.status_code == 409, r.text


def test_delete_department_detaches_users(client, admin_id, guinea_id):
    """Deleting a unit detaches its users (department set to none) rather than deleting them."""
    import uuid as _uuid
    r = client.post("/api/departments", json={"actor_id": admin_id, "name": f"יחידה זמנית {_uuid.uuid4().hex[:6]}"})
    did = r.json()["id"]
    client.patch(f"/api/users/{guinea_id}", json={"actor_id": admin_id, "department_id": did})
    assert next(u for u in client.get("/api/users").json() if u["id"] == guinea_id)["department_id"] == did
    d = client.delete(f"/api/departments/{did}?actor_id={admin_id}")
    assert d.status_code == 200, d.text
    # the user survives, just detached
    survivor = next(u for u in client.get("/api/users").json() if u["id"] == guinea_id)
    assert survivor["department_id"] is None
