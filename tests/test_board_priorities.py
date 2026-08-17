"""עמודת "עדיפות" היא עמודת סטטוס — ולכן כל מה שסטטוס יודע, גם היא יודעת.

A board admin renames, recolours, reorders, adds and removes the values of the
priority column, up to 30 of them. Five can be a Priority enum value (what
sorting and the charts read); anything beyond behaves as one of those five,
carrying its own label and colour on the item. A new item starts with nothing
chosen, which the client shows as the grey "טרם הוגדר" default.
"""
import pytest

import backend.main as cityos_main  # noqa: F401  (imported for the caps below)


def _board(client, admin_id, name="לוח עדיפויות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _get(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}?user_id={admin_id}").json()


def _set(client, bid, admin_id, priorities):
    return client.patch(f"/api/boards/{bid}",
                        json={"user_id": admin_id, "priorities": priorities})


def test_a_board_starts_with_the_five_defaults(client, admin_id):
    bid = _board(client, admin_id)
    prios = _get(client, bid, admin_id)["priorities"]
    assert [p["key"] for p in prios] == ["low", "medium", "high", "critical", "emergency"]
    assert prios[0]["label"] == "נמוכה"
    assert all(p["base"] == p["key"] for p in prios)   # each is its own engine value


def test_an_admin_renames_recolours_and_reorders(client, admin_id):
    bid = _board(client, admin_id)
    r = _set(client, bid, admin_id, [
        {"key": "high", "label": "דחוף", "color": "#e2445c"},
        {"key": "low", "label": "יכול לחכות", "color": "#00c875"},
    ])
    assert r.status_code == 200
    prios = _get(client, bid, admin_id)["priorities"]
    assert [(p["key"], p["label"], p["color"]) for p in prios] == [
        ("high", "דחוף", "#e2445c"), ("low", "יכול לחכות", "#00c875")]


def test_a_sixth_priority_is_board_defined_and_gets_a_minted_key(client, admin_id):
    """Only five keys are engine values — beyond them the board defines its own."""
    bid = _board(client, admin_id)
    base = [{"key": k, "label": k} for k in
            ("low", "medium", "high", "critical", "emergency")]
    r = _set(client, bid, admin_id, base + [{"label": "בוער", "color": "#bb3354",
                                             "base": "critical"}])
    assert r.status_code == 200
    minted = r.json()["priorities"][5]
    assert minted["key"].startswith("x_")     # the server minted it
    assert minted["label"] == "בוער"
    assert minted["base"] == "critical"       # what sorting and the charts see


def test_the_response_carries_the_priorities_back(client, admin_id):
    """The client cannot know a minted key unless the save returns it."""
    bid = _board(client, admin_id)
    r = _set(client, bid, admin_id, [{"label": "חדשה", "color": "#a25ddc"}])
    assert [p["label"] for p in r.json()["priorities"]] == ["חדשה"]


def test_up_to_thirty(client, admin_id):
    bid = _board(client, admin_id)
    r = _set(client, bid, admin_id, [{"label": f"ע{i}"} for i in range(40)])
    assert len(r.json()["priorities"]) == cityos_main.BOARD_PRIORITY_MAX == 30


def test_an_unknown_key_is_dropped_not_stored(client, admin_id):
    bid = _board(client, admin_id)
    r = _set(client, bid, admin_id, [{"key": "low", "label": "נמוכה"},
                                     {"key": "made_up", "label": "לא קיים"}])
    assert [p["key"] for p in r.json()["priorities"]] == ["low"]


def test_an_empty_list_is_refused(client, admin_id):
    bid = _board(client, admin_id)
    assert _set(client, bid, admin_id, []).status_code == 400


def test_only_a_board_admin_may_edit_them(client, admin_id, member_id):
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"user_id": member_id, "role": "editor", "actor_id": admin_id})
    r = client.patch(f"/api/boards/{bid}",
                     json={"user_id": member_id, "priorities": [{"label": "שלי"}]})
    assert r.status_code == 403


def test_each_board_keeps_its_own(client, admin_id):
    a, b = _board(client, admin_id, "א"), _board(client, admin_id, "ב")
    _set(client, a, admin_id, [{"key": "low", "label": "רק בלוח א"}])
    assert _get(client, a, admin_id)["priorities"][0]["label"] == "רק בלוח א"
    assert [p["key"] for p in _get(client, b, admin_id)["priorities"]] == [
        "low", "medium", "high", "critical", "emergency"]


# ── how an item carries a chosen priority ────────────────────────────────

def _task(client, bid, admin_id, **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                           "user_id": admin_id, **kw}).json()


def test_a_new_item_has_no_priority_chosen(client, admin_id):
    bid = _board(client, admin_id)
    t = _task(client, bid, admin_id)
    assert t["custom_fields"].get("priority_unset") is True
    assert t["priority"] == "medium"      # sorting and the charts still work


def test_naming_a_priority_on_creation_is_a_choice(client, admin_id):
    bid = _board(client, admin_id)
    t = _task(client, bid, admin_id, priority="high")
    assert t["priority"] == "high"
    assert "priority_unset" not in (t["custom_fields"] or {})


def test_creating_with_a_board_defined_priority(client, admin_id):
    """It is not an enum value — it is stored as its base, with its own label."""
    bid = _board(client, admin_id)
    base = [{"key": k, "label": k} for k in
            ("low", "medium", "high", "critical", "emergency")]
    r = _set(client, bid, admin_id, base + [{"label": "בוער", "color": "#bb3354",
                                             "base": "critical"}])
    key = r.json()["priorities"][5]["key"]
    t = _task(client, bid, admin_id, priority=key)
    assert t["priority"] == "critical"                       # the engine value
    assert t["custom_fields"]["priority_key"] == key         # what the cell shows
    assert t["custom_fields"]["priority_label"] == "בוער"
    assert "priority_unset" not in t["custom_fields"]


def test_updating_to_a_board_defined_priority(client, admin_id):
    bid = _board(client, admin_id)
    base = [{"key": k, "label": k} for k in
            ("low", "medium", "high", "critical", "emergency")]
    key = _set(client, bid, admin_id,
               base + [{"label": "בוער", "base": "critical"}]).json()["priorities"][5]["key"]
    t = _task(client, bid, admin_id)
    client.patch(f"/api/tasks/{t['id']}", json={"user_id": admin_id, "priority": key})
    fresh = [x for x in _get(client, bid, admin_id)["tasks"] if x["id"] == t["id"]][0]
    assert fresh["priority"] == "critical"
    assert fresh["custom_fields"]["priority_label"] == "בוער"
    assert "priority_unset" not in fresh["custom_fields"]


def test_choosing_a_plain_priority_clears_the_label(client, admin_id):
    """Going back to one of the five must not leave a stale board-defined label."""
    bid = _board(client, admin_id)
    base = [{"key": k, "label": k} for k in
            ("low", "medium", "high", "critical", "emergency")]
    key = _set(client, bid, admin_id,
               base + [{"label": "בוער", "base": "critical"}]).json()["priorities"][5]["key"]
    t = _task(client, bid, admin_id, priority=key)
    client.patch(f"/api/tasks/{t['id']}", json={"user_id": admin_id, "priority": "low"})
    fresh = [x for x in _get(client, bid, admin_id)["tasks"] if x["id"] == t["id"]][0]
    assert fresh["priority"] == "low"
    assert "priority_key" not in (fresh["custom_fields"] or {})
    assert "priority_label" not in (fresh["custom_fields"] or {})


def test_an_unknown_priority_key_leaves_the_item_alone(client, admin_id):
    """A key this board never defined must not crash the request or the item."""
    bid = _board(client, admin_id)
    t = _task(client, bid, admin_id, priority="high")
    r = client.patch(f"/api/tasks/{t['id']}", json={"user_id": admin_id,
                                                    "priority": "x_nonexistent"})
    assert r.status_code == 200
    fresh = [x for x in _get(client, bid, admin_id)["tasks"] if x["id"] == t["id"]][0]
    assert fresh["priority"] == "high"


def test_creating_with_an_unknown_priority_does_not_500(client, admin_id):
    bid = _board(client, admin_id)
    t = _task(client, bid, admin_id, priority="x_nope")
    assert t["priority"] == "medium"


def test_the_starter_items_of_a_new_board_have_nothing_chosen(client, admin_id):
    """A board's three sample items are items like any other — nobody picked
    a status or a priority for them either."""
    bid = _board(client, admin_id)
    tasks = _get(client, bid, admin_id)["tasks"]
    assert len(tasks) == 3
    for t in tasks:
        cf = t.get("custom_fields") or {}
        assert cf.get("priority_unset") is True
        assert cf.get("status_unset") is True
