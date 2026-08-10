"""Board-admin column management: hide/restore built-ins, reorder, rename.

Covers the three capabilities added for board admins:
  1. hide (delete) a built-in default column — except the "פריט" name column
  2. rename a built-in default column
  3. reorder columns (persisted col_order)
Plus the permission boundary (non-admins are rejected).
"""


def _make_board(client, admin_id):
    r = client.post("/api/boards", json={"name": "עמודות", "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _board(client, bid, uid):
    return client.get(f"/api/boards/{bid}?user_id={uid}").json()


def test_hide_builtin_column_persists(client, admin_id):
    bid = _make_board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}", json={"col_hidden": ["tags", "priority"], "user_id": admin_id})
    assert r.status_code == 200, r.text
    assert _board(client, bid, admin_id)["col_hidden"] == ["tags", "priority"]


def test_item_column_can_never_be_hidden(client, admin_id):
    bid = _make_board(client, admin_id)
    client.patch(f"/api/boards/{bid}", json={"col_hidden": ["item", "due"], "user_id": admin_id})
    # "item" is filtered out; only the real hideable column survives
    assert _board(client, bid, admin_id)["col_hidden"] == ["due"]


def test_unknown_keys_are_ignored_on_hide(client, admin_id):
    bid = _make_board(client, admin_id)
    client.patch(f"/api/boards/{bid}", json={"col_hidden": ["status", "bogus", 123], "user_id": admin_id})
    assert _board(client, bid, admin_id)["col_hidden"] == ["status"]


def test_reorder_columns_persists(client, admin_id):
    bid = _make_board(client, admin_id)
    order = ["item", "status", "due", "assignees", "tags", "priority"]
    r = client.patch(f"/api/boards/{bid}", json={"col_order": order, "user_id": admin_id})
    assert r.status_code == 200, r.text
    assert _board(client, bid, admin_id)["col_order"] == order


def test_reorder_dedupes(client, admin_id):
    bid = _make_board(client, admin_id)
    client.patch(f"/api/boards/{bid}", json={"col_order": ["item", "due", "due", "status"], "user_id": admin_id})
    assert _board(client, bid, admin_id)["col_order"] == ["item", "due", "status"]


def test_board_admin_can_rename_builtin(client, admin_id):
    bid = _make_board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}", json={"col_labels": {"due": "דדליין"}, "user_id": admin_id})
    assert r.status_code == 200, r.text
    assert _board(client, bid, admin_id)["col_labels"].get("due") == "דדליין"


def test_sub_item_columns_are_independent_of_the_item_columns(client, admin_id):
    """A sub-item's structure is uniform across the board but need not match the
    item's: the board admin picks which columns exist on sub-item rows."""
    bid = _make_board(client, admin_id)
    # never configured → null, meaning sub-items mirror the item columns
    assert _board(client, bid, admin_id)["sub_cols"] is None

    # a custom column, so the pool holds more than the built-ins
    r = client.patch(f"/api/boards/{bid}",
                     json={"columns": [{"type": "number", "title": "שעות"}], "user_id": admin_id})
    col_id = r.json()["columns"][0]["id"]

    r = client.patch(f"/api/boards/{bid}",
                     json={"sub_cols": ["status", col_id, "bogus"], "user_id": admin_id})
    assert r.status_code == 200, r.text
    # unknown ids dropped, the name column is always present and first
    assert _board(client, bid, admin_id)["sub_cols"] == ["item", "status", col_id]

    # the item columns are untouched by the sub-item structure
    assert _board(client, bid, admin_id)["col_hidden"] == []

    # an empty pick leaves sub-items with just their name
    client.patch(f"/api/boards/{bid}", json={"sub_cols": [], "user_id": admin_id})
    assert _board(client, bid, admin_id)["sub_cols"] == ["item"]


def test_non_admin_cannot_manage_columns(client, admin_id, member_id):
    """A board member (editor, not admin) cannot hide/reorder/rename columns."""
    bid = _make_board(client, admin_id)
    client.post(f"/api/boards/{bid}/members", json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    for payload in ({"col_hidden": ["tags"]}, {"col_order": ["item", "tags"]}, {"col_labels": {"due": "x"}},
                    {"sub_cols": ["status"]}):
        payload["user_id"] = member_id
        r = client.patch(f"/api/boards/{bid}", json=payload)
        assert r.status_code == 403, f"{payload} -> {r.status_code}"
