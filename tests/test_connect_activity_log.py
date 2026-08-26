"""What the activity log says about a link being made, removed or swapped.

Every entry names the item, not its id — an id in a log is not a record of what
happened to anyone reading it — and every entry is cut down to the links the
reader is allowed to see.
"""
import json

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _set(client, tid, col_id, ids, uid):
    return client.patch(f"/api/tasks/{tid}?user_id={uid}",
                        json={"custom_fields": {col_id: ids}}, headers=AS(uid))


def _cell(client, tid, col_id, uid):
    t = client.get(f"/api/tasks/{tid}", headers=AS(uid)).json()
    return (t.get("custom_fields") or {}).get(col_id) or []


def _setup(client, admin_id, tag, two_way=True):
    a, b = _board(client, admin_id, f"מקור {tag}"), _board(client, admin_id, f"יעד {tag}")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    return a, b, next(x for x in _cols(client, a) if x["type"] == "connect")


def _log(client, tid, uid):
    return client.get(f"/api/tasks/{tid}/activity", headers=AS(uid)).json()["activity"]


def _link_rows(client, tid, col_id, uid):
    return [r for r in _log(client, tid, uid) if r["field"] == "col:" + col_id]


# ── the three events ────────────────────────────────────────────────────────

def test_creating_a_link_is_recorded_with_the_item_and_who_did_it(client, admin_id):
    a, b, c = _setup(client, admin_id, "g1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "היעד")
    _set(client, src, c["id"], [x], admin_id)
    row = _link_rows(client, src, c["id"], admin_id)[0]
    assert json.loads(row["old"]) == []
    assert json.loads(row["new"]) == [{"id": x, "title": "היעד"}]
    assert row["user_id"] == admin_id and row["user_name"]
    assert row["created_at"], "no time on the record"


def test_removing_a_link_is_recorded_with_the_item(client, admin_id):
    a, b, c = _setup(client, admin_id, "g2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "היעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [], admin_id)
    row = _link_rows(client, src, c["id"], admin_id)[0]        # newest first
    assert json.loads(row["old"]) == [{"id": x, "title": "היעד"}]
    assert json.loads(row["new"]) == []


def test_replacing_is_one_record_showing_both_items(client, admin_id):
    a, b, c = _setup(client, admin_id, "g3")
    src = _item(client, a, admin_id, "מקור")
    x, y = _item(client, b, admin_id, "הישן"), _item(client, b, admin_id, "החדש")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [y], admin_id)
    row = _link_rows(client, src, c["id"], admin_id)[0]
    assert json.loads(row["old"]) == [{"id": x, "title": "הישן"}]
    assert json.loads(row["new"]) == [{"id": y, "title": "החדש"}]


def test_it_names_the_item_rather_than_its_id(client, admin_id):
    a, b, c = _setup(client, admin_id, "g4")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "שם ברור")
    _set(client, src, c["id"], [x], admin_id)
    assert "שם ברור" in _link_rows(client, src, c["id"], admin_id)[0]["new"]


def test_a_one_way_column_is_logged_the_same(client, admin_id):
    a, b, c = _setup(client, admin_id, "g5", two_way=False)
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "היעד")
    _set(client, src, c["id"], [x], admin_id)
    assert json.loads(_link_rows(client, src, c["id"], admin_id)[0]["new"]) == \
        [{"id": x, "title": "היעד"}]


def test_the_board_log_carries_the_same_records(client, admin_id):
    a, b, c = _setup(client, admin_id, "g6")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "היעד")
    _set(client, src, c["id"], [x], admin_id)
    rows = client.get(f"/api/boards/{a}/activity", headers=AS(admin_id)).json()["activity"]
    row = next(r for r in rows if r["field"] == "col:" + c["id"])
    assert row["task_id"] == src and "היעד" in row["new"]


# ── subject to view permissions ─────────────────────────────────────────────

def test_a_reader_sees_only_the_links_they_may_see(client, admin_id, guinea_id):
    a = _board(client, admin_id, "מקור g7")
    seen_b, closed_b = _board(client, admin_id, "גלוי g7"), _board(client, admin_id, "סגור g7")
    for bid in (a, seen_b):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [seen_b, closed_b],
                                            "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in _cols(client, a) if x["type"] == "connect")
    src = _item(client, a, admin_id, "מקור")
    ok, secret = _item(client, seen_b, admin_id, "גלוי"), _item(client, closed_b, admin_id, "סוד")
    _set(client, src, c["id"], [ok, secret], admin_id)
    mine = _link_rows(client, src, c["id"], guinea_id)[0]
    assert json.loads(mine["new"]) == [{"id": ok, "title": "גלוי"}]
    assert "סוד" not in mine["new"] and str(secret) not in mine["new"]


def test_a_change_that_was_entirely_invisible_is_not_listed(client, admin_id, guinea_id):
    """Otherwise the row confirms that something happened out of sight."""
    a, closed_b = _board(client, admin_id, "מקור g8"), _board(client, admin_id, "סגור g8")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [closed_b], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in _cols(client, a) if x["type"] == "connect")
    src = _item(client, a, admin_id, "מקור")
    _set(client, src, c["id"], [_item(client, closed_b, admin_id, "סוד")], admin_id)
    assert _link_rows(client, src, c["id"], admin_id), "the admin's own record is missing"
    assert _link_rows(client, src, c["id"], guinea_id) == []


# ── undoing one ─────────────────────────────────────────────────────────────

def test_undoing_a_link_change_actually_puts_it_back(client, admin_id):
    """The generic revert wrote the old ids into custom_fields, where a two-way
    cell's value does not live — so the undo reported success and changed
    nothing at all."""
    a, b, c = _setup(client, admin_id, "u1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "היעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [], admin_id)
    assert _cell(client, src, c["id"], admin_id) == []
    log_id = _link_rows(client, src, c["id"], admin_id)[0]["id"]
    r = client.post(f"/api/activity/{log_id}/undo", json={"actor_id": admin_id})
    assert r.status_code == 200
    assert _cell(client, src, c["id"], admin_id) == [x], "the undo did nothing"


def test_undoing_the_creation_of_a_link_removes_it_from_both_sides(client, admin_id):
    a, b, c = _setup(client, admin_id, "u2")
    mirror = c["connect"]["mirror"][str(b)]
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "היעד")
    _set(client, src, c["id"], [x], admin_id)
    log_id = _link_rows(client, src, c["id"], admin_id)[0]["id"]
    client.post(f"/api/activity/{log_id}/undo", json={"actor_id": admin_id})
    assert _cell(client, src, c["id"], admin_id) == []
    assert _cell(client, x, mirror, admin_id) == [], "the far side still shows it"


def test_undoing_a_one_way_link_change_works_too(client, admin_id):
    a, b, c = _setup(client, admin_id, "u3", two_way=False)
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "היעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [], admin_id)
    log_id = _link_rows(client, src, c["id"], admin_id)[0]["id"]
    client.post(f"/api/activity/{log_id}/undo", json={"actor_id": admin_id})
    assert _cell(client, src, c["id"], admin_id) == [x]
