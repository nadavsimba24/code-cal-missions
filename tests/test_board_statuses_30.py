"""סטטוסי לוח — עד 30.

Only seven statuses can be a TaskStatus value; those are what the engine keys
off for group auto-move, kanban and charts. A board may define up to 30, and
each one beyond the seven behaves as one of them (`base`) while carrying its
own label and colour.
"""
import main as cityos_main


def _board(client, admin_id, name="לוח סטטוסים"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _set(client, bid, admin_id, statuses):
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "statuses": statuses})
    assert r.status_code == 200, r.text
    return r.json()["statuses"]


BASE = [{"key": "todo", "label": "לביצוע", "color": "#c4c4c4"},
        {"key": "in_progress", "label": "בתהליך", "color": "#fdab3d"},
        {"key": "done", "label": "הושלם", "color": "#00c875"}]


def test_a_board_can_define_thirty_statuses(client, admin_id):
    bid = _board(client, admin_id)
    extra = [{"label": f"שלב {i}", "color": "#a25ddc", "base": "in_progress"} for i in range(27)]
    out = _set(client, bid, admin_id, BASE + extra)
    assert len(out) == 30
    assert sum(1 for s in out if s["key"] == s["base"]) == 3        # the built-ins
    assert sum(1 for s in out if s["key"] != s["base"]) == 27       # board-defined


def test_beyond_the_cap_is_trimmed(client, admin_id):
    bid = _board(client, admin_id)
    many = BASE + [{"label": f"ש{i}", "color": "#a25ddc"} for i in range(40)]
    assert len(_set(client, bid, admin_id, many)) == cityos_main.BOARD_STATUS_MAX


def test_a_board_defined_status_gets_a_key_and_a_base(client, admin_id):
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE + [{"label": "ממתין לספק", "color": "#a25ddc",
                                               "base": "on_hold"}])
    made = out[-1]
    assert made["key"].startswith("x_") and made["key"] not in cityos_main._STATUS_KEYS
    assert made["base"] == "on_hold" and made["label"] == "ממתין לספק"


def test_an_unknown_base_falls_back_to_a_real_one(client, admin_id):
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE + [{"label": "מוזר", "base": "not-a-status"}])
    assert out[-1]["base"] in cityos_main._STATUS_KEYS


def test_the_seven_built_ins_keep_their_own_key_as_base(client, admin_id):
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE)
    assert all(s["base"] == s["key"] for s in out)


def test_an_item_stores_the_base_and_carries_the_label(client, admin_id):
    """This is what keeps auto-move, kanban and the charts working."""
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE + [{"label": "בבדיקת קבלן", "color": "#a25ddc",
                                               "base": "in_progress"}])
    custom = out[-1]
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={
        "user_id": admin_id, "status": custom["base"],
        "custom_fields": {"status_key": custom["key"], "status_label": custom["label"],
                          "status_color": custom["color"]}})
    task = [t for t in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"]
            if t["id"] == tid][0]
    assert task["status"] == "in_progress"                     # the engine's value
    assert task["custom_fields"]["status_label"] == "בבדיקת קבלן"
    # and it landed in the group that matches the base status
    groups = {g["id"]: g for g in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["groups"]}
    assert groups[task["group_id"]]["task_status"] in ("in_progress", "review", "on_hold")


def test_statuses_come_back_from_the_patch(client, admin_id):
    """The client cannot know the key the server minted otherwise."""
    bid = _board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}",
                     json={"user_id": admin_id, "statuses": BASE + [{"label": "חדש"}]})
    assert "statuses" in r.json() and len(r.json()["statuses"]) == 4


def test_non_admin_cannot_change_them(client, admin_id, member_id):
    bid = _board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}", json={"user_id": member_id, "statuses": BASE})
    assert r.status_code == 403
