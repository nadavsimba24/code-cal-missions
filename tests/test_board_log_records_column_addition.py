"""הוספת עמודה מופיעה בלוג הלוח, לא רק המחיקה.

Deleting a column left a line; adding one left nothing. The reason is in the
shape of the save: the loop that writes those lines walks `old_cols`, the
columns the board had BEFORE the request, so it can only ever see a column
that already existed. A column that was not there is not in that dictionary
and was never reached.

The log therefore read as a board that only ever lost columns — a deletion
with no matching creation anywhere behind it, and no way to answer "who added
this, and when" about a column that is still there.

Both halves of the pair are pinned here, because a line that only appears for
one of them is the bug this closes. The wording is pinned by
tests/frontend/column_restore_line.mjs.
"""
COL = {"id": "col_add1", "title": "תקציב", "type": "number"}


def _board(client, admin_id):
    return client.post("/api/boards", json={"name": "לוח עמודות",
                                            "user_id": admin_id}).json()["id"]


def _cols(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]


def _column_lines(client, bid, admin_id):
    rows = client.get(f"/api/boards/{bid}/activity?user_id={admin_id}").json()["activity"]
    return [r for r in rows if r["field"] == "column"]


def test_adding_a_column_is_written_to_the_board_log(client, admin_id):
    bid = _board(client, admin_id)
    try:
        # the board's automatic columns are kept — replacing the whole array
        # with one column would delete them, and those deletions are not what
        # this is about
        client.patch(f"/api/boards/{bid}",
                     json={"columns": _cols(client, bid, admin_id) + [dict(COL)],
                           "user_id": admin_id})
        made = [r for r in _column_lines(client, bid, admin_id) if r["action"] == "create"]
        assert len(made) == 1, made
        assert made[0]["new"] == "תקציב"
        assert made[0]["task_id"] is None      # it happened to the board
        assert made[0]["user_id"] == admin_id
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_pair_reads_as_a_pair(client, admin_id):
    """Add then remove: two lines, in that order, naming the same column."""
    bid = _board(client, admin_id)
    try:
        client.patch(f"/api/boards/{bid}",
                     json={"columns": _cols(client, bid, admin_id) + [dict(COL)],
                           "user_id": admin_id})
        client.patch(f"/api/boards/{bid}",
                     json={"columns": [c for c in _cols(client, bid, admin_id)
                                       if c["id"] != COL["id"]],
                           "user_id": admin_id})
        lines = _column_lines(client, bid, admin_id)
        # newest first
        assert [l["action"] for l in lines] == ["delete", "create"], lines
        assert lines[0]["old"] == "תקציב" and lines[1]["new"] == "תקציב"
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_touching_a_board_without_adding_one_writes_nothing(client, admin_id):
    """A save that changes something else must not report a column it did not
    add — every column in the request already exists, so none is new."""
    bid = _board(client, admin_id)
    try:
        cols = _cols(client, bid, admin_id)
        client.patch(f"/api/boards/{bid}", json={"columns": cols, "user_id": admin_id})
        assert _column_lines(client, bid, admin_id) == []
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_a_refused_save_records_neither_half(client, admin_id):
    """A 409 is the whole request refused, not the deletion half of it.

    The forms gate stops a save that would remove a column a form still
    asks about. A request can carry an addition and a removal together, so
    the "create" lines are written after that gate for the same reason the
    deletions are: a change that did not happen must not leave a line saying
    it did. Placement is the whole of this guarantee, and placement is easy
    to lose in a reshuffle — hence a test rather than a comment.
    """
    AS = {"X-CityOS-User": str(admin_id)}
    bid = client.post("/api/boards", json={"name": "שער הטפסים"}, headers=AS).json()["id"]
    try:
        cols = [dict(c) for c in client.get(f"/api/boards/{bid}", headers=AS).json()["columns"]]
        client.patch(f"/api/boards/{bid}",
                     json={"columns": cols + [{"id": "col_gate", "title": "שדה בטופס",
                                               "type": "text"}]}, headers=AS)
        f = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS).json()
        client.patch(f"/api/forms/{f['id']}",
                     json={"components": [{"kind": "question", "field_key": "col_gate",
                                           "label": "שדה בטופס"}]}, headers=AS)

        live = [dict(c) for c in client.get(f"/api/boards/{bid}", headers=AS).json()["columns"]]
        before = len(_column_lines(client, bid, admin_id))

        # one request: drop the column the form needs AND add another
        r = client.patch(f"/api/boards/{bid}",
                         json={"columns": [c for c in live if c["id"] != "col_gate"]
                                          + [{"id": "col_new", "title": "חדשה", "type": "text"}]},
                         headers=AS)
        assert r.status_code == 409, r.text

        after = _column_lines(client, bid, admin_id)
        assert len(after) == before, \
            f"a refused save still wrote {len(after) - before} column line(s): {after[:2]}"
        assert not [a for a in after if a["new"] == "חדשה"], \
            "the addition in a refused request was recorded"
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")
