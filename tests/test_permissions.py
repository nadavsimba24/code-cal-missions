"""Group 10 — configurable role→capability matrix and its enforcement."""


def _matrix(client):
    return client.get("/api/role-permissions").json()


def test_matrix_shape_and_admin_locked(client):
    """The matrix exposes capabilities, roles (incl. locked admin + guest), and grid."""
    d = _matrix(client)
    caps = {c["key"] for c in d["capabilities"]}
    import main as cityos_main
    assert caps == set(cityos_main.CAPABILITIES), "the screen and the server disagree"
    assert {"manage_system", "create_environment", "create_board"} <= caps
    assert all(c.get("label") or c.get("he") or c.get("name") for c in d["capabilities"]), \
        "a capability with no name to show"
    role_keys = {r["key"] for r in d["roles"]}
    assert {"admin", "manager", "member", "viewer", "guest"} <= role_keys
    admin = next(r for r in d["roles"] if r["key"] == "admin")
    assert admin["locked"] is True
    # admin always has every capability
    assert all(d["matrix"]["admin"][c] for c in caps)


def test_defaults_are_all_false_for_non_admin(client):
    """Out of the box a non-admin role has no capability — except the ones
    CAP_DEFAULT_ON names, and naming them there is the whole point.

    A capability is normally a power granted: nobody had it until somebody said
    so, so False is the only safe thing to be born with. export_excel and
    download_files are the other kind — they describe something every role could
    already do, written down so that it can be taken away from אורח. Born False
    they would have taken Excel and every attachment away from every member of
    every board on the first restart after they were added, which is the bug this
    test would then have been pinning in place."""
    import main as cityos_main
    d = _matrix(client)
    for role in ("manager", "member", "viewer", "guest"):
        for cap, allowed in d["matrix"][role].items():
            on_by_default = role in cityos_main.CAP_DEFAULT_ON.get(cap, ())
            assert allowed is on_by_default, \
                f"{role} should start {'with' if on_by_default else 'without'} {cap}"
    # and the one role the exceptions exist for starts without them
    for cap in cityos_main.CAP_DEFAULT_ON:
        assert d["matrix"]["guest"][cap] is False, cap


def test_non_admin_cannot_edit_matrix(client, member_id):
    """A non-admin cannot toggle the matrix → 403."""
    r = client.put("/api/role-permissions", json={"actor_id": member_id, "role": "guest",
                                                  "capability": "create_board", "allowed": True})
    assert r.status_code == 403, r.text


def test_grant_create_board_lets_member_create(client, admin_id, guinea_id):
    """Granting 'create_board' to the member role lets a plain member create a board."""
    # baseline: member cannot create a board
    r = client.post("/api/boards", json={"name": "לפני הרשאה", "user_id": guinea_id})
    assert r.status_code == 403, r.text
    try:
        g = client.put("/api/role-permissions", json={"actor_id": admin_id, "role": "member",
                                                      "capability": "create_board", "allowed": True})
        assert g.status_code == 200, g.text
        r = client.post("/api/boards", json={"name": "אחרי הרשאה", "user_id": guinea_id})
        assert r.status_code == 200, r.text
        client.delete(f"/api/boards/{r.json()['id']}?user_id={guinea_id}")
    finally:
        client.put("/api/role-permissions", json={"actor_id": admin_id, "role": "member",
                                                  "capability": "create_board", "allowed": False})
    # revoked again
    r = client.post("/api/boards", json={"name": "אחרי ביטול", "user_id": guinea_id})
    assert r.status_code == 403, r.text


def test_grant_manage_system_lets_member_add_user(client, admin_id, guinea_id):
    """Granting 'manage_system' lets a member hit an admin-only endpoint (create user)."""
    import uuid as _uuid
    email = f"perm_{_uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/users", json={"actor_id": guinea_id, "name": "לא מורשה", "email": email})
    assert r.status_code == 403, r.text
    try:
        client.put("/api/role-permissions", json={"actor_id": admin_id, "role": "member",
                                                  "capability": "manage_system", "allowed": True})
        r = client.post("/api/users", json={"actor_id": guinea_id, "name": "מורשה", "email": email})
        assert r.status_code == 200, r.text
    finally:
        client.put("/api/role-permissions", json={"actor_id": admin_id, "role": "member",
                                                  "capability": "manage_system", "allowed": False})


def test_bad_role_or_capability_rejected(client, admin_id):
    """The admin role can't be edited via the matrix, and unknown caps are rejected."""
    r = client.put("/api/role-permissions", json={"actor_id": admin_id, "role": "admin",
                                                  "capability": "create_board", "allowed": False})
    assert r.status_code == 400, r.text
    r = client.put("/api/role-permissions", json={"actor_id": admin_id, "role": "guest",
                                                  "capability": "fly_to_moon", "allowed": True})
    assert r.status_code == 400, r.text
