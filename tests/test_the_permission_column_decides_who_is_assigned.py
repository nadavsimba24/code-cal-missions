"""Which column says who is "assigned" is a setting of the board.

The assigned_editor and assigned_only roles reach an item because they are
assigned to it (test_a_board_role_can_reach_only_assigned_items.py). Many boards
do not track ownership in the built-in אחראים column at all — they have their own
people column ("מבצע", "אחראי שטח") and leave אחראים empty. So the board names
its permission column in `settings.perm_column`: "assignees" for the built-in
one, or the id of one of its own people columns.

Pinned here:

* unset, the board reads "assignees" — every board that existed before the
  setting behaves as it always would have;
* only the board's admin may change it, because changing it re-decides who can
  see what on the whole board in one stroke;
* it must name something that can hold people — a text column or a column that
  does not exist would quietly make nobody assigned to anything;
* and access really does follow it: switching columns moves who reaches which
  item, and switching back moves it back.
"""
import pytest

from conftest import join_primary_env


def AS(uid):
    return {"X-CityOS-User": str(uid)}


def _user(client, admin_id, name, email):
    for u in client.get("/api/users", headers=AS(admin_id)).json():
        if u.get("email") == email:
            uid = u["id"]
            break
    else:
        r = client.post("/api/users", headers=AS(admin_id),
                        json={"name": name, "email": email, "role": "member"})
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
    join_primary_env(client, uid)
    return uid


def _board_json(client, bid, uid):
    r = client.get(f"/api/boards/{bid}", headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _perm_column(client, bid, uid):
    return (_board_json(client, bid, uid).get("settings") or {}).get("perm_column")


def _rows(client, bid, uid):
    return {t["id"]: t.get("my_perm") for t in _board_json(client, bid, uid)["tasks"]
            if not t.get("parent_id")}


def _item(client, admin_id, bid, title):
    r = client.post("/api/tasks", headers=AS(admin_id), json={"board_id": bid, "title": title})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _set(client, bid, uid, value):
    return client.patch(f"/api/boards/{bid}", headers=AS(uid), json={"perm_column": value})


@pytest.fixture
def ae(client, admin_id):
    return _user(client, admin_id, "בודק עורך משויכים", "test.assigned.editor@cityos.test")


@pytest.fixture
def ao(client, admin_id):
    return _user(client, admin_id, "בודק משויכים בלבד", "test.assigned.only@cityos.test")


@pytest.fixture
def board(client, admin_id, ae, ao, guinea_id):
    """A board with its own people column "ppl" and a text column "txt",
    an assigned_editor, an assigned_only member and a plain editor."""
    r = client.post("/api/boards", headers=AS(admin_id), json={"name": "לוח עמודת הרשאה"})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        join_primary_env(client, guinea_id)
        for uid, role in ((ae, "assigned_editor"), (ao, "assigned_only"), (guinea_id, "editor")):
            r = client.post(f"/api/boards/{bid}/members", headers=AS(admin_id),
                            json={"user_id": uid, "role": role})
            assert r.status_code == 200, r.text
        cols = _board_json(client, bid, admin_id)["columns"] + [
            {"id": "ppl", "type": "people", "title": "מבצע"},
            {"id": "txt", "type": "text", "title": "הערה"}]
        r = client.patch(f"/api/boards/{bid}", headers=AS(admin_id), json={"columns": cols})
        assert r.status_code == 200, r.text
        yield bid
    finally:
        client.delete(f"/api/boards/{bid}", headers=AS(admin_id))


def test_a_board_that_never_chose_reads_the_built_in_assignees(client, admin_id, board):
    assert _perm_column(client, board, admin_id) == "assignees"


def test_only_the_board_admin_may_choose_the_permission_column(
        client, admin_id, ae, ao, guinea_id, board):
    for uid in (guinea_id, ae, ao):
        r = _set(client, board, uid, "ppl")
        assert r.status_code == 403, f"user {uid}: {r.status_code} {r.text}"
    assert _perm_column(client, board, admin_id) == "assignees", "a refused change still landed"
    r = _set(client, board, admin_id, "ppl")
    assert r.status_code == 200, r.text
    assert _perm_column(client, board, admin_id) == "ppl"
    r = _set(client, board, admin_id, "assignees")
    assert r.status_code == 200, r.text
    assert _perm_column(client, board, admin_id) == "assignees"


@pytest.mark.parametrize("value", ["txt", "no_such_column", "", "status"])
def test_a_column_that_cannot_hold_people_is_refused(client, admin_id, board, value):
    """A permission column nobody can be named in would make nobody assigned to
    anything — every assigned_only member would open an empty board."""
    r = _set(client, board, admin_id, value)
    assert r.status_code == 400, r.text
    assert _perm_column(client, board, admin_id) == "assignees"


def test_switching_to_a_people_column_moves_who_reaches_which_item(client, admin_id, ae, ao, board):
    by_assignee = _item(client, admin_id, board, "משויך באחראים")
    by_column = _item(client, admin_id, board, "משויך בעמודה")
    for uid in (ae, ao):
        r = client.post(f"/api/tasks/{by_assignee}/assignees", headers=AS(admin_id),
                        json={"user_id": uid, "action": "add"})
        assert r.status_code == 200, r.text

    # before: the built-in column decides
    assert set(_rows(client, board, ao)) == {by_assignee}
    assert _rows(client, board, ae).get(by_assignee) == "edit"

    assert _set(client, board, admin_id, "ppl").status_code == 200
    # ppl is now the permission column, so naming them in it is allowed
    r = client.patch(f"/api/tasks/{by_column}", headers=AS(admin_id),
                     json={"custom_fields": {"ppl": [ae, ao]}})
    assert r.status_code == 200, r.text
    stored = next(t for t in _board_json(client, board, admin_id)["tasks"]
                  if t["id"] == by_column)["custom_fields"].get("ppl") or []
    assert ae in stored and ao in stored, stored

    # after: the people column decides, and the old assignment counts for nothing
    rows = _rows(client, board, ao)
    assert set(rows) == {by_column}, rows
    assert rows[by_column] == "edit"
    rows = _rows(client, board, ae)
    assert rows.get(by_column) == "edit" and rows.get(by_assignee) == "view", rows
    assert client.patch(f"/api/tasks/{by_column}", headers=AS(ao),
                        json={"title": "עודכן דרך העמודה"}).status_code == 200
    assert client.patch(f"/api/tasks/{by_assignee}", headers=AS(ae),
                        json={"title": "לא"}).status_code == 403

    # and back again
    assert _set(client, board, admin_id, "assignees").status_code == 200
    assert set(_rows(client, board, ao)) == {by_assignee}
    rows = _rows(client, board, ae)
    assert rows.get(by_assignee) == "edit" and rows.get(by_column) == "view", rows


def test_the_count_and_the_search_follow_the_permission_column_too(client, admin_id, ao, board):
    """The count is computed in SQL and the search down its own path; both
    have to read the board's column, not assume the built-in one."""
    only = _item(client, admin_id, board, "בעמודה בלבד")
    assert _set(client, board, admin_id, "ppl").status_code == 200
    r = client.patch(f"/api/tasks/{only}", headers=AS(admin_id),
                     json={"custom_fields": {"ppl": [ao]}})
    assert r.status_code == 200, r.text

    assert _board_json(client, board, ao)["item_count"] == 1
    r = client.post(f"/api/boards/{board}/items/query", headers=AS(ao),
                    json={"filter": {"operator": "and", "rules": []}, "ids_only": True})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1 and r.json()["item_ids"] == [only], r.json()
    r = client.get("/api/items/search", headers=AS(ao), params={"board_ids": str(board)})
    assert {it["id"] for it in r.json()["items"]} == {only}
