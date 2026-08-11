"""Group 6 — login history (recording + admin-only visibility)."""


def _last_login(client, uid):
    return next(u for u in client.get("/api/users").json() if u["id"] == uid)["last_login"]


def test_record_login(client, guinea_id):
    """POST /api/auth/login records an event and returns its timestamp."""
    r = client.post("/api/auth/login", json={"user_id": guinea_id})
    assert r.status_code == 200, r.text
    assert r.json().get("logged_in_at")


def test_record_login_unknown_user_404(client):
    """Recording a login for a non-existent user returns 404."""
    assert client.post("/api/auth/login", json={"user_id": 999999}).status_code == 404


def test_last_login_reflected(client, guinea_id):
    """After a login, the user's last_login in /api/users is populated."""
    client.post("/api/auth/login", json={"user_id": guinea_id})
    assert _last_login(client, guinea_id) is not None


def test_per_user_history_admin_only(client, admin_id, member_id, guinea_id):
    """Per-user login history: admin sees events (200); non-admin is denied (403)."""
    client.post("/api/auth/login", json={"user_id": guinea_id})
    ok = client.get(f"/api/users/{guinea_id}/login-history?actor_id={admin_id}")
    assert ok.status_code == 200
    assert len(ok.json()) >= 1
    assert ok.json()[0].get("logged_in_at")
    denied = client.get(f"/api/users/{guinea_id}/login-history?actor_id={member_id}")
    assert denied.status_code == 403


def test_consolidated_history_admin_only(client, admin_id, member_id, guinea_id):
    """Consolidated login history (all users): admin sees named events; non-admin denied (403)."""
    client.post("/api/auth/login", json={"user_id": guinea_id})
    ok = client.get(f"/api/login-history?actor_id={admin_id}")
    assert ok.status_code == 200
    events = ok.json()
    assert len(events) >= 1
    assert "user_name" in events[0]
    denied = client.get(f"/api/login-history?actor_id={member_id}")
    assert denied.status_code == 403
