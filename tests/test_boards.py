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


def test_board_admin_who_is_not_a_workspace_admin_can_delete(client, admin_id, guinea_id):
    """The board menu offers "מחק לוח" to a board admin, so the API must allow it."""
    bid = client.post("/api/boards", json={"name": "לוח של מנהל לוח", "user_id": admin_id}).json()["id"]
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    assert client.get(f"/api/boards/{bid}?user_id={guinea_id}").json()["my_role"] == "admin"
    assert client.delete(f"/api/boards/{bid}?user_id={guinea_id}").status_code in (200, 204)
    assert client.get(f"/api/boards/{bid}?user_id={admin_id}").status_code == 404


def test_editor_cannot_delete_a_board(client, admin_id, guinea_id):
    bid = client.post("/api/boards", json={"name": "לוח של עורך", "user_id": admin_id}).json()["id"]
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert client.delete(f"/api/boards/{bid}?user_id={guinea_id}").status_code == 403
    assert client.get(f"/api/boards/{bid}?user_id={admin_id}").status_code == 200
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")


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


def test_board_add_remove_notifies_user(client, admin_id, guinea_id):
    """Adding a user to a board (any role) notifies them; removing them notifies too.
    A plain role change (not a new add) does not create an extra 'add' notification."""
    # baseline unread count for the guinea user
    base = client.get(f"/api/notifications?user_id={guinea_id}").json()["unread_count"]
    r = client.post("/api/boards", json={"name": "notif board", "department_id": 1, "user_id": admin_id})
    bid = r.json()["id"]
    try:
        # add (viewer) → one notification
        client.post(f"/api/boards/{bid}/members", json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
        n = client.get(f"/api/notifications?user_id={guinea_id}").json()
        assert n["unread_count"] == base + 1
        assert n["notifications"][0]["type"] == "board_add"
        assert n["notifications"][0]["board_id"] == bid
        # role change (already a member) → no new notification
        client.post(f"/api/boards/{bid}/members", json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
        assert client.get(f"/api/notifications?user_id={guinea_id}").json()["unread_count"] == base + 1
        # remove → another notification
        client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
        n = client.get(f"/api/notifications?user_id={guinea_id}").json()
        assert n["unread_count"] == base + 2
        assert n["notifications"][0]["type"] == "board_remove"
        # mark-all-read clears the count
        client.post("/api/notifications/read-all", json={"user_id": guinea_id})
        assert client.get(f"/api/notifications?user_id={guinea_id}").json()["unread_count"] == 0
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_board_notifications_can_be_switched_off(client, admin_id, guinea_id):
    """A board admin can switch off notifications for a board; add/remove then
    produce no notifications. Non-admins can't toggle it."""
    base = client.get(f"/api/notifications?user_id={guinea_id}").json()["unread_count"]
    r = client.post("/api/boards", json={"name": "quiet board", "department_id": 1, "user_id": admin_id})
    bid = r.json()["id"]
    try:
        # default on
        assert client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["notifications_enabled"] is True
        # switch off (admin)
        r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "notifications_enabled": False})
        assert r.status_code == 200, r.text
        assert client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["notifications_enabled"] is False
        # add + remove while off → no notifications
        client.post(f"/api/boards/{bid}/members", json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
        client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
        assert client.get(f"/api/notifications?user_id={guinea_id}").json()["unread_count"] == base
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_non_admin_cannot_toggle_board_notifications(client, member_id):
    """A non-admin board member cannot toggle board notifications → 403."""
    r = client.patch("/api/boards/1", json={"user_id": member_id, "notifications_enabled": False})
    assert r.status_code == 403


def test_connect_column_requires_system_admin(client, admin_id, guinea_id):
    """Adding/changing a cross-board 'connect' column requires a workspace admin;
    a board admin who isn't a workspace admin is refused, but may still edit other
    columns and pass the existing connect column through unchanged."""
    r = client.post("/api/boards", json={"name": "connect board", "department_id": 1, "user_id": admin_id})
    bid = r.json()["id"]
    try:
        r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [
            {"type": "connect", "title": "קישור", "connect": {"board_ids": [1], "multiple": True}}]})
        assert r.status_code == 200, r.text
        cols = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
        con = [c for c in cols if c["type"] == "connect"]
        assert con and con[0]["connect"]["board_ids"] == [1]
        # promote guinea to board admin — still NOT a workspace admin
        client.post(f"/api/boards/{bid}/members", json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
        # guinea adds a new connect column → 403
        r = client.patch(f"/api/boards/{bid}", json={"user_id": guinea_id, "columns": cols + [
            {"type": "connect", "title": "עוד", "connect": {"board_ids": [1], "multiple": False}}]})
        assert r.status_code == 403, r.text
        # guinea keeps the existing connect column unchanged → allowed
        r = client.patch(f"/api/boards/{bid}", json={"user_id": guinea_id, "columns": cols})
        assert r.status_code == 200, r.text
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_items_search_and_lookup(client, admin_id):
    """The connect picker's search + the display lookup return items with board names."""
    tasks = client.get(f"/api/boards/1?user_id={admin_id}").json()["tasks"]
    assert tasks
    tid, title = tasks[0]["id"], tasks[0]["title"]
    items = client.get("/api/items/search?board_ids=1").json()["items"]
    assert any(it["id"] == tid for it in items)
    assert all("board_name" in it for it in items)
    # search filters by title, and excludes a given task
    filt = client.get(f"/api/items/search?board_ids=1&exclude_task={tid}").json()["items"]
    assert all(it["id"] != tid for it in filt)
    look = client.get(f"/api/tasks/lookup?ids={tid}").json()["items"]
    assert look and look[0]["id"] == tid and look[0]["title"] == title and look[0]["board_id"] == 1


def test_connect_cell_link_add_remove_replace(client, admin_id):
    """A connect cell stores only references; add / replace / remove / clear all
    persist as a plain id list without touching the linked items."""
    r = client.post("/api/boards", json={"name": "link cells", "department_id": 1, "user_id": admin_id})
    bid = r.json()["id"]
    try:
        r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [
            {"type": "connect", "title": "קישור", "connect": {"board_ids": [1], "multiple": True}}]})
        colid = [c for c in r.json()["columns"] if c["type"] == "connect"][0]["id"]
        host = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"][0]["id"]
        b1 = client.get(f"/api/boards/1?user_id={admin_id}").json()["tasks"]
        a, b = b1[0]["id"], b1[1]["id"]

        def cell():
            tasks = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"]
            t = next(x for x in tasks if x["id"] == host)
            return (t.get("custom_fields") or {}).get(colid)

        client.patch(f"/api/tasks/{host}", json={"user_id": admin_id, "custom_fields": {colid: [a]}})
        assert cell() == [a]
        client.patch(f"/api/tasks/{host}", json={"user_id": admin_id, "custom_fields": {colid: [a, b]}})
        assert cell() == [a, b]
        client.patch(f"/api/tasks/{host}", json={"user_id": admin_id, "custom_fields": {colid: [b]}})   # replace/remove
        assert cell() == [b]
        client.patch(f"/api/tasks/{host}", json={"user_id": admin_id, "custom_fields": {colid: None}})   # clear
        assert cell() in (None, [])
        # linked items themselves are untouched
        assert client.get(f"/api/boards/1?user_id={admin_id}").json()["tasks"], "linked board still intact"
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_connect_config_change_requires_sysadmin(client, admin_id, guinea_id):
    """Changing a connect column's target boards needs a workspace admin; a board
    admin who isn't a workspace admin is refused."""
    r = client.post("/api/boards", json={"name": "cfg board", "department_id": 1, "user_id": admin_id})
    bid = r.json()["id"]
    try:
        r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [
            {"type": "connect", "title": "קישור", "connect": {"board_ids": [1], "multiple": True}}]})
        cols = r.json()["columns"]
        client.post(f"/api/boards/{bid}/members", json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
        changed = [{**cols[0], "connect": {"board_ids": [1, 2], "multiple": True}}]
        assert client.patch(f"/api/boards/{bid}", json={"user_id": guinea_id, "columns": changed}).status_code == 403
        assert client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": changed}).status_code == 200
        got = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"][0]
        assert got["connect"]["board_ids"] == [1, 2]
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_items_search_query_filters(client, admin_id):
    """Item search matches by title and returns nothing for a non-matching query;
    lookup handles empty and multiple ids."""
    b1 = client.get(f"/api/boards/1?user_id={admin_id}").json()["tasks"]
    word = b1[0]["title"].split()[0]
    hit = client.get("/api/items/search", params={"board_ids": "1", "q": word}).json()["items"]
    assert any(word in it["title"] for it in hit)
    miss = client.get("/api/items/search", params={"board_ids": "1", "q": "zzq_nomatch_9"}).json()["items"]
    assert miss == []
    assert client.get("/api/tasks/lookup", params={"ids": ""}).json()["items"] == []
    ids = f"{b1[0]['id']},{b1[1]['id']}"
    got = {it["id"] for it in client.get("/api/tasks/lookup", params={"ids": ids}).json()["items"]}
    assert got == {b1[0]["id"], b1[1]["id"]}


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
