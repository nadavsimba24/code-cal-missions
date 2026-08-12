"""עמודות אוטומטיות — "מועד יצירה" ו"יוצר הרשומה".

Both are derived from the item itself, so adding them to an *existing* board
must work exactly as on a freshly created one — including for items that were
created before the column was added. The creator column used to be a plain
people column auto-filled only when it carried the hardcoded id
`sys_created_by`, so on any existing board it stayed empty forever.
"""


def _board(client, admin_id, name="לוח קיים"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _set_cols(client, bid, admin_id, cols):
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": cols})
    assert r.status_code == 200, r.text
    return r.json()["columns"]


def _task(client, bid, admin_id, title="פריט", **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **kw}).json()


def _items(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"]


def test_new_board_ships_with_both_auto_columns(client, admin_id):
    bid = _board(client, admin_id, "לוח חדש")
    cols = {c["id"]: c["type"] for c in
            client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]}
    assert cols.get("sys_created_at") == "created_at"
    assert cols.get("sys_created_by") == "created_by"


def test_creator_column_can_be_added_to_an_existing_board(client, admin_id):
    """The regression: on an existing board the column has a generated id."""
    bid = _board(client, admin_id)
    _set_cols(client, bid, admin_id, [])                       # an "old" board, no auto columns
    before = _task(client, bid, admin_id, "פריט שנוצר לפני העמודה")
    cols = _set_cols(client, bid, admin_id, [{"type": "created_at", "title": "מועד יצירה"},
                                             {"type": "created_by", "title": "יוצר הרשומה"}])
    assert [c["type"] for c in cols] == ["created_at", "created_by"]
    assert not any(c["id"].startswith("sys_") for c in cols)    # ids are generated, not magic

    after = _task(client, bid, admin_id, "פריט שנוצר אחרי העמודה")
    # both columns read from the item, so both items carry the data they render
    for t in (before, after):
        fresh = [x for x in _items(client, bid, admin_id) if x["id"] == t["id"]][0]
        assert fresh["created_by"] == admin_id
        assert fresh["created_at"]


def test_sub_items_carry_creator_and_creation_time(client, admin_id):
    bid = _board(client, admin_id)
    parent = _task(client, bid, admin_id, "אב")
    _task(client, bid, admin_id, "תת-פריט", parent_id=parent["id"])
    sub = [x for x in _items(client, bid, admin_id) if x["id"] == parent["id"]][0]["subtasks"][0]
    assert sub["created_by"] == admin_id and sub["created_at"]


def test_legacy_people_creator_column_still_auto_fills(client, admin_id):
    """Boards created before the change carry it as a people column."""
    bid = _board(client, admin_id)
    _set_cols(client, bid, admin_id, [{"id": "sys_created_by", "type": "people",
                                       "title": "יוצר הרשומה"}])
    t = _task(client, bid, admin_id)
    assert t["custom_fields"].get("sys_created_by") == [admin_id]


def test_derived_creator_column_stores_no_cell_value(client, admin_id):
    """Nothing to fill in — the value is the item's own creator."""
    bid = _board(client, admin_id)
    cols = _set_cols(client, bid, admin_id, [{"type": "created_by", "title": "יוצר הרשומה"}])
    t = _task(client, bid, admin_id)
    assert cols[0]["id"] not in (t["custom_fields"] or {})
    assert t["created_by"] == admin_id


def test_created_by_is_a_valid_column_type(client, admin_id):
    bid = _board(client, admin_id)
    assert _set_cols(client, bid, admin_id, [{"type": "created_by", "title": "יוצר"}])
    # an unknown type is still dropped
    assert _set_cols(client, bid, admin_id, [{"type": "bogus", "title": "לא קיים"}]) == []
