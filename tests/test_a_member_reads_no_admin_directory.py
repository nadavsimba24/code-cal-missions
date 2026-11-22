"""The organisation's directory is the system administrator's, not every member's.

The penetration test of 2026-11 read five administrative listings with a
member's session and got the same answer an administrator gets: every user's
address, phone and last sign-in (/api/users), every workspace member and role
(/api/workspace/members), the whole permission matrix (/api/role-permissions)
and the size and activity of every unit (/api/departments).

Pinned here, both directions: a member gets what the app needs to draw people
and gate its own features — colleagues' names and pictures, their own full row,
their own role's permissions — and nothing the directory screen is for; an
administrator still gets all of it. /api/environments was already filtered to
the caller's environments and is pinned elsewhere.
"""

H = lambda uid: {"X-CityOS-User": str(uid)}
PRIVATE = ("email", "phone", "last_login", "created_at", "notif_prefs", "email_notifications")


def test_a_member_sees_colleagues_without_their_private_details(client, member_id, admin_id):
    rows = client.get("/api/users", headers=H(member_id)).json()
    others = [u for u in rows if u["id"] != member_id]
    assert others, "the member must still see colleagues — people columns are drawn from this"
    for u in others:
        assert u.get("name") is not None and "avatar_url" in u
        leaked = [k for k in PRIVATE if k in u]
        assert not leaked, (u["id"], leaked)
    mine = next(u for u in rows if u["id"] == member_id)
    assert mine.get("email"), "the caller's own row is whole"


def test_an_administrator_still_gets_the_directory(client, admin_id):
    rows = client.get("/api/users", headers=H(admin_id)).json()
    assert any("email" in u and "last_login" in u for u in rows if u["id"] != admin_id)


def test_a_member_sees_only_their_own_workspace_row(client, member_id, admin_id):
    d = client.get("/api/workspace/members", headers=H(member_id)).json()
    assert {m["user_id"] for m in d["members"]} <= {member_id}
    assert d["available"] == []
    full = client.get("/api/workspace/members", headers=H(admin_id)).json()
    assert len(full["members"]) > 1


def test_a_member_reads_only_their_own_roles_permissions(client, member_id, admin_id):
    m = client.get("/api/role-permissions", headers=H(member_id)).json()["matrix"]
    assert set(m) <= {"admin", "member"}, set(m)
    assert "member" in m                          # hasCap needs exactly this row
    full = client.get("/api/role-permissions", headers=H(admin_id)).json()["matrix"]
    assert {"guest", "viewer", "manager"} <= set(full)


def test_a_member_sees_unit_names_but_not_their_size(client, member_id, admin_id):
    ds = client.get("/api/departments", headers=H(member_id)).json()
    for d in ds:
        assert d.get("name") is not None
        assert not {"user_count", "board_count", "active_user_count"} & set(d), d
    full = client.get("/api/departments", headers=H(admin_id)).json()
    if full:
        assert "user_count" in full[0]
