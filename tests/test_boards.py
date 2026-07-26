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


def test_board_has_default_statuses(client, admin_id):
    """Every board exposes a status list; a fresh board gets the 7 defaults."""
    r = client.post("/api/boards", json={"name": "st board", "department_id": 1, "user_id": admin_id})
    bid = r.json()["id"]
    try:
        sts = client.get(f"/api/boards/{bid}?user_id={admin_id}").json().get("statuses")
        assert isinstance(sts, list) and len(sts) == 7
        assert {s["key"] for s in sts} >= {"backlog", "in_progress", "done"}
        assert all({"key", "label", "color"} <= set(s) for s in sts)
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_board_admin_customises_statuses(client, admin_id):
    """A board admin renames/reorders statuses; unknown keys dropped, colors validated."""
    r = client.post("/api/boards", json={"name": "st2 board", "department_id": 1, "user_id": admin_id})
    bid = r.json()["id"]
    try:
        r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "statuses": [
            {"key": "backlog", "label": "בתכנון", "color": "#9699a6"},
            {"key": "in_progress", "label": "בפיתוח", "color": "#fdab3d"},
            {"key": "done", "label": "הושלם", "color": "not-a-color"},   # bad hex → default
            {"key": "bogus", "label": "X", "color": "#000000"},          # unknown key → dropped
            {"key": "backlog", "label": "dup", "color": "#111111"},      # dup → dropped
        ]})
        assert r.status_code == 200, r.text
        sts = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["statuses"]
        assert [s["key"] for s in sts] == ["backlog", "in_progress", "done"]
        assert sts[0]["label"] == "בתכנון"
        assert sts[2]["color"] == "#c4c4c4"   # invalid hex fell back to default
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_non_admin_cannot_customise_statuses(client, member_id):
    """A non-admin board member cannot edit statuses → 403."""
    r = client.patch("/api/boards/1", json={"user_id": member_id,
                                            "statuses": [{"key": "done", "label": "X", "color": "#00c875"}]})
    assert r.status_code == 403


def test_sysadmin_renames_item_column(client, admin_id):
    """A workspace (system) admin renames the built-in 'פריט' column; it persists.
    Only built-in keys are accepted, blank/unknown dropped."""
    r = client.patch("/api/boards/1", json={"user_id": admin_id, "col_labels": {
        "item": "משימה", "bogus": "x", "status": "  "}})
    assert r.status_code == 200, r.text
    cl = client.get(f"/api/boards/1?user_id={admin_id}").json().get("col_labels", {})
    assert cl.get("item") == "משימה"
    assert "bogus" not in cl and "status" not in cl
    # restore default (empty label removed)
    client.patch("/api/boards/1", json={"user_id": admin_id, "col_labels": {}})


def test_non_sysadmin_cannot_rename_column(client, member_id):
    """A non-workspace-admin cannot rename a built-in column → 403."""
    r = client.patch("/api/boards/1", json={"user_id": member_id, "col_labels": {"item": "x"}})
    assert r.status_code == 403


def test_inviting_new_member_flags_invited(client, admin_id, guinea_id):
    """Inviting a genuinely new member returns invited=True (triggers the email);
    a follow-up role change on the same member returns invited=False (no email).
    Email delivery itself no-ops without RESEND_API_KEY, so the invite never fails."""
    r = client.post("/api/boards", json={"name": "invite test", "department_id": 1, "user_id": admin_id})
    bid = r.json()["id"]
    try:
        r = client.post(f"/api/boards/{bid}/members", json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
        assert r.status_code == 200 and r.json().get("invited") is True, r.text
        r = client.post(f"/api/boards/{bid}/members", json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
        assert r.status_code == 200 and r.json().get("invited") is False, r.text
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")
