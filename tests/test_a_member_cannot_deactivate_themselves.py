"""PATCH /api/users/{id} judges the whole request before it changes anything.

The penetration test of 2026-11 found the route enforced the administrator
check on some sensitive fields and not others: a member's {"role": "admin"}
was refused, but their own email was accepted, and the recorded sequence ended
with the member deactivating their own account and locking themselves out.

Pinned here: a member cannot change their own status, role or department; a
request mixing an allowed field with a forbidden one is refused as a whole and
changes nothing; resending a value unchanged is not a change; and the last
active system administrator cannot be deactivated or demoted.
"""

H = lambda uid: {"X-CityOS-User": str(uid)}


def _make(client, admin_id, email, role="member"):
    r = client.post("/api/users", json={"name": "בודק", "email": email, "role": role},
                    headers=H(admin_id))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _row(client, admin_id, uid):
    return next(u for u in client.get("/api/users", headers=H(admin_id)).json() if u["id"] == uid)


def test_a_member_cannot_deactivate_themselves_and_stays_signed_in(client, admin_id):
    uid = _make(client, admin_id, "self-deact@example.com")
    try:
        r = client.patch(f"/api/users/{uid}", json={"is_active": False}, headers=H(uid))
        assert r.status_code == 403, r.text
        assert client.get("/api/auth/me", headers=H(uid)).status_code == 200
        for body in ({"role": "admin"}, {"department_id": 1}):
            assert client.patch(f"/api/users/{uid}", json=body, headers=H(uid)).status_code == 403
    finally:
        client.delete(f"/api/users/{uid}", headers=H(admin_id))


def test_a_mixed_request_is_refused_whole_and_changes_nothing(client, admin_id):
    uid = _make(client, admin_id, "mixed-req@example.com")
    try:
        r = client.patch(f"/api/users/{uid}", json={"title": "שונה", "is_active": False},
                         headers=H(uid))
        assert r.status_code == 403, r.text
        row = _row(client, admin_id, uid)
        assert row.get("title") != "שונה" and row["is_active"] is True
    finally:
        client.delete(f"/api/users/{uid}", headers=H(admin_id))


def test_resending_the_current_values_is_not_a_change(client, admin_id):
    """A whole-row save sends role and status as they already are."""
    uid = _make(client, admin_id, "same-vals@example.com")
    try:
        r = client.patch(f"/api/users/{uid}",
                         json={"role": "member", "is_active": True, "title": "רכזת"},
                         headers=H(uid))
        assert r.status_code == 200 and r.json()["title"] == "רכזת"
    finally:
        client.delete(f"/api/users/{uid}", headers=H(admin_id))


def test_the_last_active_administrator_is_not_removed(client, admin_id):
    """With one other administrator, demoting is allowed; with none, it is not.
    Asked on a second admin so the fixture admin is never touched."""
    other = _make(client, admin_id, "second-admin@example.com", role="admin")
    try:
        # two active admins: the second may be demoted
        r = client.patch(f"/api/users/{other}", json={"role": "member"}, headers=H(admin_id))
        assert r.status_code == 200, r.text
        client.patch(f"/api/users/{other}", json={"role": "admin"}, headers=H(admin_id))
        # an admin may never deactivate their own row
        r = client.patch(f"/api/users/{other}", json={"is_active": False}, headers=H(other))
        assert r.status_code == 400, r.text
    finally:
        client.delete(f"/api/users/{other}", headers=H(admin_id))
