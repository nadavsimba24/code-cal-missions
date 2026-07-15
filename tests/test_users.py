"""Group 5 — user management (system-admin directory)."""
import pytest


def _get_user(client, uid):
    return next(u for u in client.get("/api/users").json() if u["id"] == uid)


def test_users_list_shape(client):
    """/api/users exposes the fields the admin directory needs."""
    u = client.get("/api/users").json()[0]
    for key in ("id", "name", "role", "is_active", "department_name", "last_login"):
        assert key in u, f"user missing '{key}'"


def test_non_admin_cannot_change_role(client, member_id, guinea_id):
    """A non-admin member cannot change another user's role → 403."""
    r = client.patch(f"/api/users/{guinea_id}", json={"actor_id": member_id, "role": "admin"})
    assert r.status_code == 403, r.text


def test_admin_cannot_deactivate_self(client, admin_id):
    """An admin cannot deactivate their own account → 400 (lockout guard)."""
    r = client.patch(f"/api/users/{admin_id}", json={"actor_id": admin_id, "is_active": False})
    assert r.status_code == 400, r.text


def test_admin_changes_role_and_restores(client, admin_id, guinea_id):
    """An admin can change a user's role; the test restores it afterwards."""
    original = _get_user(client, guinea_id)["role"]
    try:
        r = client.patch(f"/api/users/{guinea_id}", json={"actor_id": admin_id, "role": "viewer"})
        assert r.status_code == 200, r.text
        assert _get_user(client, guinea_id)["role"] == "viewer"
    finally:
        client.patch(f"/api/users/{guinea_id}", json={"actor_id": admin_id, "role": original})


def test_admin_toggles_active_and_restores(client, admin_id, guinea_id):
    """An admin can deactivate then reactivate a user (the status toggle path)."""
    try:
        r = client.patch(f"/api/users/{guinea_id}", json={"actor_id": admin_id, "is_active": False})
        assert r.status_code == 200, r.text
        assert _get_user(client, guinea_id)["is_active"] is False
        r = client.patch(f"/api/users/{guinea_id}", json={"actor_id": admin_id, "is_active": True})
        assert r.status_code == 200
        assert _get_user(client, guinea_id)["is_active"] is True
    finally:
        client.patch(f"/api/users/{guinea_id}", json={"actor_id": admin_id, "is_active": True})
