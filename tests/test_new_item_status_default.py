"""פריט חדש — סטטוס ברירת מחדל "טרם הוגדר".

A new item has no status yet: every status column on it reads the grey
"טרם הוגדר" default until someone picks one. The underlying task.status still
carries the group's value, so group auto-move, the kanban and the charts keep
working — the mark only says that no human has chosen.
"""


def _board(client, admin_id, name="לוח פריט חדש"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _task(client, bid, admin_id, **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                           "user_id": admin_id, **kw}).json()


def _fresh(client, bid, admin_id, tid):
    return [t for t in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"]
            if t["id"] == tid][0]


def test_a_new_item_has_no_chosen_status(client, admin_id):
    bid = _board(client, admin_id)
    t = _task(client, bid, admin_id)
    assert t["custom_fields"].get("status_unset") is True


def test_it_still_carries_an_engine_status_for_grouping(client, admin_id):
    """The default is about display — grouping must not be disturbed."""
    bid = _board(client, admin_id)
    gid = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["groups"][0]["id"]
    t = _task(client, bid, admin_id, group_id=gid)       # as the UI creates one
    assert t["status"]                                   # a real TaskStatus value
    assert t["group_id"] == gid                          # and it sits in that group
    assert t["custom_fields"].get("status_unset") is True


def test_choosing_a_status_clears_the_mark(client, admin_id):
    bid = _board(client, admin_id)
    t = _task(client, bid, admin_id)
    client.patch(f"/api/tasks/{t['id']}", json={
        "user_id": admin_id, "status": "done",
        "custom_fields": {"status_unset": None, "status_key": None, "status_label": None}})
    fresh = _fresh(client, bid, admin_id, t["id"])
    assert fresh["status"] == "done"
    assert "status_unset" not in (fresh["custom_fields"] or {})


def test_naming_a_status_on_creation_is_a_choice(client, admin_id):
    """The form and a move name a status — that is not "not yet chosen"."""
    bid = _board(client, admin_id)
    t = _task(client, bid, admin_id, status="in_progress")
    assert t["status"] == "in_progress"
    assert "status_unset" not in (t["custom_fields"] or {})


def test_a_sub_item_gets_the_same_default(client, admin_id):
    bid = _board(client, admin_id)
    parent = _task(client, bid, admin_id)
    sub = _task(client, bid, admin_id, parent_id=parent["id"])
    assert sub["custom_fields"].get("status_unset") is True


def test_custom_status_columns_start_empty(client, admin_id):
    """Nothing is written into them — the grey default is what an empty cell shows."""
    bid = _board(client, admin_id)
    col = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [
        {"type": "status", "title": "שלב", "options": [{"label": "א", "color": "#0073ea"}]}]}
    ).json()["columns"][0]
    t = _task(client, bid, admin_id)
    assert col["id"] not in (t["custom_fields"] or {})
