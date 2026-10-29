"""Deleting a column is a board event, and the board's log says so.

"מחיקת עמודה בלוח צריכה להופיע בלוגים". Until this existed the log was built
entirely out of AuditLog rows whose entity is a task, so a column — which
belongs to the board and takes a field off every item at once — vanished
without leaving a trace anywhere: no name, no actor, no time.

What is pinned here is the whole path, because each half is useless alone:
the row is written (backend/main.py, update_board) AND the board log reads
rows whose entity is the board (_board_activity_rows). It is also pinned that
such a row is not mistaken for an item: it carries no task_id, so the page
draws no "open the item" button, and it can never be undone.
"""
AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    r = client.post("/api/boards", json={"name": name, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _cols(client, bid, uid):
    return [dict(c) for c in client.get(f"/api/boards/{bid}", headers=AS(uid)).json()["columns"]]


def _add_col(client, bid, uid, title, ctype="text"):
    cols = _cols(client, bid, uid)
    cols.append({"type": ctype, "title": title})
    r = client.patch(f"/api/boards/{bid}", json={"columns": cols}, headers=AS(uid))
    assert r.status_code == 200, r.text
    return [c["id"] for c in r.json()["columns"] if c.get("title") == title][0]


def _drop_col(client, bid, uid, col_id):
    cols = [c for c in _cols(client, bid, uid) if c["id"] != col_id]
    r = client.patch(f"/api/boards/{bid}", json={"columns": cols}, headers=AS(uid))
    assert r.status_code == 200, r.text


def _log(client, bid, uid, **params):
    r = client.get(f"/api/boards/{bid}/activity", headers=AS(uid), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_deleting_a_column_writes_a_line_naming_it(client, admin_id):
    bid = _board(client, admin_id, "לוג מחיקת עמודה")
    cid = _add_col(client, bid, admin_id, "תקציב מאושר")
    _drop_col(client, bid, admin_id, cid)

    rows = [a for a in _log(client, bid, admin_id)["activity"] if a["field"] == "column"]
    assert rows, "deleting a column left nothing in the board's log"
    assert rows[0]["action"] == "delete"
    # the column itself no longer exists, so this row is the only place its
    # name survives — a line that cannot say WHICH column is not an answer
    assert rows[0]["old"] == "תקציב מאושר"
    assert rows[0]["user_id"] == admin_id


def test_the_line_belongs_to_the_board_and_not_to_an_item(client, admin_id):
    """No task_id, so the page draws no 'open the item' button, and no undo.

    The board's id would otherwise arrive in task_id and collide with whatever
    item happens to carry that number.
    """
    bid = _board(client, admin_id, "לוג עמודה ללא פריט")
    cid = _add_col(client, bid, admin_id, "עמודה חולפת")
    _drop_col(client, bid, admin_id, cid)

    row = next(a for a in _log(client, bid, admin_id)["activity"] if a["field"] == "column")
    assert row["task_id"] is None
    assert row["can_undo"] is False
    assert row["task_title"] == "לוג עמודה ללא פריט", "the line has to say what it is about"


def test_a_board_with_no_items_still_shows_it(client, admin_id):
    """The log used to return early when the board had no items at all.

    Every row it could read belonged to an item, so an empty board could not
    have a history. A column deletion is a history an empty board can have,
    and the early return swallowed it.
    """
    bid = _board(client, admin_id, "לוח ריק עם לוג")
    cid = _add_col(client, bid, admin_id, "עמודה בלוח ריק")
    _drop_col(client, bid, admin_id, cid)

    rows = [a for a in _log(client, bid, admin_id)["activity"] if a["field"] == "column"]
    assert [r["old"] for r in rows] == ["עמודה בלוח ריק"]


def test_an_undo_of_that_row_is_refused(client, admin_id):
    """The gate, not the hint: there is no old value to put back."""
    bid = _board(client, admin_id, "לוג עמודה בלי ביטול")
    cid = _add_col(client, bid, admin_id, "עמודה למחיקה")
    _drop_col(client, bid, admin_id, cid)

    row = next(a for a in _log(client, bid, admin_id)["activity"] if a["field"] == "column")
    r = client.post(f"/api/activity/{row['id']}/undo", json={}, headers=AS(admin_id))
    assert r.status_code == 400


def test_whoever_deleted_the_column_can_be_filtered_to(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוג עמודה לפי מבצע")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    cid = _add_col(client, bid, guinea_id, "עמודה של בודק")
    _drop_col(client, bid, guinea_id, cid)

    d = _log(client, bid, admin_id)
    assert guinea_id in {p["id"] for p in d["people"]}
    only = _log(client, bid, admin_id, user_id=guinea_id)["activity"]
    assert [a["old"] for a in only if a["field"] == "column"] == ["עמודה של בודק"]


def test_a_rename_is_not_a_deletion(client, admin_id):
    """The id carries on, so nothing was deleted — the header just says
    something else now. A log that calls that a deletion is worse than one
    that misses it."""
    bid = _board(client, admin_id, "לוג שינוי שם עמודה")
    cid = _add_col(client, bid, admin_id, "שם ראשון")
    cols = _cols(client, bid, admin_id)
    for c in cols:
        if c["id"] == cid:
            c["title"] = "שם שני"
    assert client.patch(f"/api/boards/{bid}", json={"columns": cols},
                        headers=AS(admin_id)).status_code == 200
    assert not [a for a in _log(client, bid, admin_id)["activity"] if a["field"] == "column"]


def test_it_is_written_once_and_not_again_on_the_next_save(client, admin_id):
    bid = _board(client, admin_id, "לוג עמודה פעם אחת")
    cid = _add_col(client, bid, admin_id, "עמודה יחידה")
    _drop_col(client, bid, admin_id, cid)
    # a second save of the same (already shorter) column list
    _drop_col(client, bid, admin_id, cid)
    rows = [a for a in _log(client, bid, admin_id)["activity"] if a["field"] == "column"]
    assert len(rows) == 1


def test_a_refused_deletion_leaves_no_line(client, admin_id):
    """A form asks about the column, so the change comes back 409 and nothing
    happened. A log line for a change that was refused is a false record."""
    bid = _board(client, admin_id, "לוג עמודה שנדחתה")
    cid = _add_col(client, bid, admin_id, "שדה בטופס")
    f = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(admin_id)).json()
    client.patch(f"/api/forms/{f['id']}", json={"components": [
        {"kind": "question", "field_key": cid, "label": "שדה בטופס"}]},
        headers=AS(admin_id))

    cols = [c for c in _cols(client, bid, admin_id) if c["id"] != cid]
    assert client.patch(f"/api/boards/{bid}", json={"columns": cols},
                        headers=AS(admin_id)).status_code == 409
    assert not [a for a in _log(client, bid, admin_id)["activity"] if a["field"] == "column"]

    # and once it IS agreed to, the line appears
    assert client.patch(f"/api/boards/{bid}",
                        json={"columns": cols, "confirm_columns": [cid]},
                        headers=AS(admin_id)).status_code == 200
    assert [a["old"] for a in _log(client, bid, admin_id)["activity"]
            if a["field"] == "column"] == ["שדה בטופס"]


def test_removing_a_builtin_column_is_logged_and_so_is_bringing_it_back(client, admin_id):
    """The "..." menu on a built-in header says מחק עמודה and this is what it
    calls. It cannot really be dropped — it is a column of the item — so the
    row says it was taken off the board, and the way back is logged too, or
    the log reads as deletions that never ended."""
    bid = _board(client, admin_id, "לוג עמודת ברירת מחדל")
    assert client.patch(f"/api/boards/{bid}", json={"col_hidden": ["due"]},
                        headers=AS(admin_id)).status_code == 200
    rows = [a for a in _log(client, bid, admin_id)["activity"] if a["field"] == "builtin_column"]
    assert [(r["action"], r["old"]) for r in rows] == [("delete", "תאריך יעד")]

    assert client.patch(f"/api/boards/{bid}", json={"col_hidden": []},
                        headers=AS(admin_id)).status_code == 200
    rows = [a for a in _log(client, bid, admin_id)["activity"] if a["field"] == "builtin_column"]
    assert [(r["action"], r["old"]) for r in rows] == [("restore", "תאריך יעד"),
                                                       ("delete", "תאריך יעד")]


def test_saving_the_same_hidden_set_twice_logs_once(client, admin_id):
    bid = _board(client, admin_id, "לוג הסתרה פעם אחת")
    for _ in range(2):
        assert client.patch(f"/api/boards/{bid}", json={"col_hidden": ["priority"]},
                            headers=AS(admin_id)).status_code == 200
    rows = [a for a in _log(client, bid, admin_id)["activity"] if a["field"] == "builtin_column"]
    assert len(rows) == 1


def test_the_export_carries_the_line_too(client, admin_id):
    bid = _board(client, admin_id, "ייצוא לוג עמודה")
    cid = _add_col(client, bid, admin_id, "עמודה מיוצאת")
    _drop_col(client, bid, admin_id, cid)
    r = client.get(f"/api/boards/{bid}/activity/export", headers=AS(admin_id))
    assert r.status_code == 200
    assert "עמודה מיוצאת" in r.text
