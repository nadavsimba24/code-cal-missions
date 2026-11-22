"""A deactivated account is refused everywhere — user management included.

The penetration test of 2026-11 reported that a session refused on ordinary
routes (/api/auth/me → 403) still created an active admin with POST /api/users
and reactivated and promoted a user with PATCH /api/users/{id}. Deactivation
is only a containment control if it holds on exactly those routes, so this
pins the reported sequence against an account that WAS a system administrator
— the one case where the routes' own permission check would otherwise pass.
"""

H = lambda uid: {"X-CityOS-User": str(uid)}


def test_a_deactivated_administrator_cannot_create_reactivate_or_promote(client, admin_id):
    made = []
    try:
        r = client.post("/api/users", json={"name": "מנהל מושבת", "email": "deact-admin@example.com",
                                            "role": "admin"}, headers=H(admin_id))
        assert r.status_code == 200, r.text
        bad = r.json()["id"]; made.append(bad)
        r = client.post("/api/users", json={"name": "יעד", "email": "deact-target@example.com",
                                            "role": "member"}, headers=H(admin_id))
        target = r.json()["id"]; made.append(target)
        assert client.patch(f"/api/users/{target}", json={"is_active": False},
                            headers=H(admin_id)).status_code == 200

        # while active, this account could do all of it — the routes' own check passes
        assert client.get("/api/auth/me", headers=H(bad)).status_code == 200
        # deactivated by another administrator
        assert client.patch(f"/api/users/{bad}", json={"is_active": False},
                            headers=H(admin_id)).status_code == 200

        # 1. the ordinary route refuses it
        assert client.get("/api/auth/me", headers=H(bad)).status_code == 403
        # 2. it cannot create a new active admin
        r = client.post("/api/users", json={"name": "recovery_admin", "email": "recovery@example.com",
                                            "role": "admin", "is_active": True}, headers=H(bad))
        assert r.status_code == 403, r.text
        # 3. nor reactivate a deactivated record, nor promote it
        assert client.patch(f"/api/users/{target}", json={"is_active": True},
                            headers=H(bad)).status_code == 403
        assert client.patch(f"/api/users/{target}", json={"role": "admin"},
                            headers=H(bad)).status_code == 403
        # nor reactivate itself
        assert client.patch(f"/api/users/{bad}", json={"is_active": True},
                            headers=H(bad)).status_code == 403

        users = {u["email"]: u for u in client.get("/api/users", headers=H(admin_id)).json()}
        assert "recovery@example.com" not in users
        t = next(u for u in users.values() if u["id"] == target)
        assert t["is_active"] is False and t["role"] == "member"
    finally:
        for uid in made:
            client.delete(f"/api/users/{uid}", headers=H(admin_id))
