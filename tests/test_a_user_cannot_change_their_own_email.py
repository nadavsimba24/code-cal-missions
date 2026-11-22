"""The address a person signs in with is not theirs to change from the profile.

Every request is resolved to a user by the email its sign-in carries. The
penetration test of 2026-11 changed a member's own address with
PATCH /api/users/{id}: the session still carried the old one, the row held the
new one, and the account locked itself out. Pointed at an address someone else
will sign in with, the same request is a claim on their account in advance.

Pinned here: a member cannot change their address, and a system administrator
cannot change their own either (the same lock-out). Another administrator can
change it, and the rest of the profile stays the member's to edit.
"""

H = lambda uid: {"X-CityOS-User": str(uid)}


def _make_user(client, admin_id, email):
    r = client.post("/api/users", json={"name": "בודק מייל", "email": email, "role": "member"},
                    headers=H(admin_id))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_a_member_cannot_change_their_own_email(client, admin_id):
    uid = _make_user(client, admin_id, "self-email-1@example.com")
    try:
        r = client.patch(f"/api/users/{uid}", json={"email": "attacker@example.com"}, headers=H(uid))
        assert r.status_code == 403, r.text
        # the account still resolves — the lock-out the test found does not happen
        me = client.get("/api/users", headers=H(uid))
        assert me.status_code == 200
        row = next(u for u in me.json() if u["id"] == uid)
        assert row["email"] == "self-email-1@example.com"
        # and everything else on the profile is still theirs
        r = client.patch(f"/api/users/{uid}", json={"phone": "050-0000000", "title": "רכז"},
                         headers=H(uid))
        assert r.status_code == 200 and r.json()["phone"] == "050-0000000"
        # sending the address unchanged, as a whole-profile save does, is not a change
        r = client.patch(f"/api/users/{uid}", json={"email": "Self-Email-1@example.com", "name": "שם חדש"},
                         headers=H(uid))
        assert r.status_code == 200 and r.json()["name"] == "שם חדש"
    finally:
        client.delete(f"/api/users/{uid}", headers=H(admin_id))


def test_an_administrator_cannot_change_their_own_email(client, admin_id):
    r = client.patch(f"/api/users/{admin_id}", json={"email": "elsewhere@example.com"},
                     headers=H(admin_id))
    assert r.status_code == 403, r.text


def test_another_administrator_changes_it_and_a_bad_one_is_refused(client, admin_id):
    uid = _make_user(client, admin_id, "self-email-2@example.com")
    try:
        r = client.patch(f"/api/users/{uid}", json={"email": "not-an-address"}, headers=H(admin_id))
        assert r.status_code == 400, r.text
        r = client.patch(f"/api/users/{uid}", json={"email": "Moved-2@Example.com"}, headers=H(admin_id))
        assert r.status_code == 200 and r.json()["email"] == "moved-2@example.com"
    finally:
        client.delete(f"/api/users/{uid}", headers=H(admin_id))
