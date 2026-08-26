"""The twelve acceptance criteria for the connect column, one test each.

Deliberately end-to-end and deliberately literal: each test is named after the
criterion it stands for, so a failure says which one regressed.
"""
from sqlalchemy import event
from sqlalchemy.orm import Session
import main as cityos_main
from models import ItemLink

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _cell(client, tid, col_id, uid):
    t = client.get(f"/api/tasks/{tid}", headers=AS(uid)).json()
    return (t.get("custom_fields") or {}).get(col_id) or []


def _set(client, tid, col_id, ids, uid):
    return client.patch(f"/api/tasks/{tid}?user_id={uid}",
                        json={"custom_fields": {col_id: ids}}, headers=AS(uid))


def _connect(client, actor, a, targets, two_way=True, multiple=True, title="קישור"):
    cols = _cols(client, a) + [{"type": "connect", "title": title,
                                "connect": {"board_ids": targets, "multiple": multiple,
                                            "two_way": two_way}}]
    r = client.patch(f"/api/boards/{a}", json={"actor_id": actor, "columns": cols},
                     headers=AS(actor))
    return r, next((x for x in _cols(client, a)
                    if x["type"] == "connect" and x["title"] == title), None)


# 1 ─────────────────────────────────────────────────────────────────────────
def test_01_a_board_admin_can_create_one_and_name_its_target_boards(client, admin_id, guinea_id):
    a, b = _board(client, admin_id, "מקור a1"), _board(client, admin_id, "יעד a1")
    # guinea administers `a` and can see `b`, but is not a workspace admin
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    client.post(f"/api/boards/{b}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    r, col = _connect(client, guinea_id, a, [b])
    assert r.status_code == 200, f"a board admin was refused: {r.text[:200]}"
    assert col is not None and col["connect"]["board_ids"] == [b]


def test_01b_a_board_admin_cannot_target_a_board_they_cannot_see(client, admin_id, guinea_id):
    """Naming target boards is not a way to reach one you were never given."""
    a, closed = _board(client, admin_id, "מקור a1b"), _board(client, admin_id, "סגור a1b")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    r, col = _connect(client, guinea_id, a, [closed])
    assert r.status_code >= 400 or not (col and closed in (col["connect"]["board_ids"] or [])), \
        "a board admin pointed a column at a board they cannot open"


# 2 ─────────────────────────────────────────────────────────────────────────
def test_02_only_items_the_user_may_view_can_be_chosen(client, admin_id, guinea_id):
    a, closed = _board(client, admin_id, "מקור a2"), _board(client, admin_id, "סגור a2")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    _, c = _connect(client, admin_id, a, [closed])
    src, secret = _item(client, a, admin_id, "מקור"), _item(client, closed, admin_id, "סוד")
    assert client.get(f"/api/items/search?board_ids={closed}",
                      headers=AS(guinea_id)).json()["items"] == []
    _set(client, src, c["id"], [secret], guinea_id)
    assert _cell(client, src, c["id"], admin_id) == []


# 3 ─────────────────────────────────────────────────────────────────────────
def test_03_single_or_several_according_to_the_column(client, admin_id):
    a, b = _board(client, admin_id, "מקור a3"), _board(client, admin_id, "יעד a3")
    _, one = _connect(client, admin_id, a, [b], multiple=False, title="יחיד")
    _, many = _connect(client, admin_id, a, [b], multiple=True, title="מרובה")
    src = _item(client, a, admin_id, "מקור")
    xs = [_item(client, b, admin_id, f"יעד {i}") for i in range(3)]
    _set(client, src, one["id"], xs, admin_id)
    _set(client, src, many["id"], xs, admin_id)
    assert len(_cell(client, src, one["id"], admin_id)) == 1
    assert sorted(_cell(client, src, many["id"], admin_id)) == sorted(xs)


# 4 ─────────────────────────────────────────────────────────────────────────
def test_04_the_link_is_the_id_and_survives_renaming(client, admin_id):
    a, b = _board(client, admin_id, "מקור a4"), _board(client, admin_id, "יעד a4")
    _, c = _connect(client, admin_id, a, [b])
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "שם ישן")
    _set(client, src, c["id"], [x], admin_id)
    client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"title": "שם חדש"})
    client.patch(f"/api/boards/{b}", json={"actor_id": admin_id, "name": "לוח בשם אחר"})
    assert _cell(client, src, c["id"], admin_id) == [x]
    e = client.get(f"/api/tasks/lookup?ids={x}", headers=AS(admin_id)).json()["items"][0]
    assert e["title"] == "שם חדש" and e["board_name"] == "לוח בשם אחר"


# 5 ─────────────────────────────────────────────────────────────────────────
def test_05_a_linked_item_can_be_opened(client, admin_id):
    a, b = _board(client, admin_id, "מקור a5"), _board(client, admin_id, "יעד a5")
    _, c = _connect(client, admin_id, a, [b])
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    r = client.get(f"/api/tasks/{x}", headers=AS(admin_id))
    assert r.status_code == 200 and r.json()["title"] == "יעד"


# 6 ─────────────────────────────────────────────────────────────────────────
def test_06_removing_a_link_deletes_no_items(client, admin_id):
    a, b = _board(client, admin_id, "מקור a6"), _board(client, admin_id, "יעד a6")
    _, c = _connect(client, admin_id, a, [b])
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [], admin_id)
    for tid in (src, x):
        assert client.get(f"/api/tasks/{tid}", headers=AS(admin_id)).status_code == 200


# 7 ─────────────────────────────────────────────────────────────────────────
def test_07_two_way_creation_and_removal_show_on_both_sides(client, admin_id):
    a, b = _board(client, admin_id, "מקור a7"), _board(client, admin_id, "יעד a7")
    _, c = _connect(client, admin_id, a, [b])
    mirror = c["connect"]["mirror"][str(b)]
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    assert _cell(client, x, mirror, admin_id) == [src]
    _set(client, x, mirror, [], admin_id)                # removed from the far side
    assert _cell(client, src, c["id"], admin_id) == []
    with Session(cityos_main.engine) as db:
        assert db.query(ItemLink).filter(
            (ItemLink.a_task_id == src) | (ItemLink.b_task_id == src)).count() == 0


# 8 ─────────────────────────────────────────────────────────────────────────
def test_08_losing_access_closes_every_route_through_the_link(client, admin_id, guinea_id):
    a, b = _board(client, admin_id, "מקור a8"), _board(client, admin_id, "יעד a8")
    for bid in (a, b):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    _, c = _connect(client, admin_id, a, [b])
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "סוד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}/members/{guinea_id}?actor_id={admin_id}")
    assert _cell(client, src, c["id"], guinea_id) == []
    look = client.get(f"/api/tasks/lookup?ids={x}", headers=AS(guinea_id)).json()["items"][0]
    assert look.get("restricted") is True and not look.get("title")
    for door in ("", "/comments", "/files", "/activity", "/activity/export"):
        assert client.get(f"/api/tasks/{x}{door}",
                          headers=AS(guinea_id)).status_code in (403, 404), door
    assert "סוד" not in client.get(f"/api/tasks/{src}/activity", headers=AS(guinea_id)).text


# 9 ─────────────────────────────────────────────────────────────────────────
def test_09_an_unavailable_target_never_leaves_a_live_broken_link(client, admin_id):
    a, b = _board(client, admin_id, "מקור a9"), _board(client, admin_id, "יעד a9")
    _, c = _connect(client, admin_id, a, [b])
    src = _item(client, a, admin_id, "מקור")
    binned, purged = _item(client, b, admin_id, "לסל"), _item(client, b, admin_id, "לצמיתות")
    _set(client, src, c["id"], [binned, purged], admin_id)
    client.delete(f"/api/tasks/{binned}?user_id={admin_id}")
    client.delete(f"/api/tasks/{purged}?user_id={admin_id}")
    client.delete(f"/api/boards/{b}/trash/{purged}?actor_id={admin_id}")
    cell = _cell(client, src, c["id"], admin_id)
    assert purged not in cell, "an active link to a destroyed item"
    assert cell == [binned], "the recoverable one was dropped instead of marked"
    assert client.get(f"/api/tasks/lookup?ids={binned}",
                      headers=AS(admin_id)).json()["items"][0]["deleted"] is True
    client.post(f"/api/tasks/{binned}/restore", json={"actor_id": admin_id})
    assert client.get(f"/api/tasks/lookup?ids={binned}",
                      headers=AS(admin_id)).json()["items"][0]["deleted"] is False


# 10 ────────────────────────────────────────────────────────────────────────
def test_10_adding_and_removing_are_written_to_the_activity_log(client, admin_id):
    import json
    a, b = _board(client, admin_id, "מקור a10"), _board(client, admin_id, "יעד a10")
    _, c = _connect(client, admin_id, a, [b])
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "היעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [], admin_id)
    rows = [r for r in client.get(f"/api/tasks/{src}/activity",
                                  headers=AS(admin_id)).json()["activity"]
            if r["field"] == "col:" + c["id"]]
    assert len(rows) == 2
    removal, addition = rows[0], rows[1]        # newest first
    assert json.loads(addition["new"]) == [{"id": x, "title": "היעד"}]
    assert json.loads(removal["old"]) == [{"id": x, "title": "היעד"}] and json.loads(removal["new"]) == []
    assert all(r["user_id"] == admin_id and r["created_at"] for r in rows)


# 11 ────────────────────────────────────────────────────────────────────────
def test_11_the_column_can_carry_a_mirror_field(client, admin_id):
    a, b = _board(client, admin_id, "מקור a11"), _board(client, admin_id, "יעד a11")
    _, c = _connect(client, admin_id, a, [b])
    cols = _cols(client, a) + [{"type": "mirror", "title": "סטטוס מקושר",
                                "mirror_of": {"connect": c["id"], "field": "status"}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    mir = next(x for x in _cols(client, a) if x["type"] == "mirror")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"status": "done"})
    _set(client, src, c["id"], [x], admin_id)
    cell = _cell(client, src, mir["id"], admin_id)
    assert [e["text"] for e in cell] == ["הושלם"]
    client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"status": "in_progress"})
    assert [e["text"] for e in _cell(client, src, mir["id"], admin_id)] == ["בתהליך"]


# 12 ────────────────────────────────────────────────────────────────────────
def test_12_the_board_loads_without_the_target_boards_data(client, admin_id):
    a, b = _board(client, admin_id, "מקור a12"), _board(client, admin_id, "יעד a12")
    _, c = _connect(client, admin_id, a, [b])
    far = [_item(client, b, admin_id, f"רחוק ייחודי {i}") for i in range(20)]
    near = [_item(client, a, admin_id, f"קרוב {i}") for i in range(10)]
    for t in near:
        _set(client, t, c["id"], far[:2], admin_id)
    body = client.get(f"/api/boards/{a}", headers=AS(admin_id)).text
    assert "רחוק ייחודי" not in body, "the payload carried the target board's items"
    assert "יעד a12" not in body, "the payload carried the target board's name"

    n = {"q": 0}
    h = lambda *args, **kw: n.__setitem__("q", n["q"] + 1)
    event.listen(cityos_main.engine, "before_cursor_execute", h)
    client.get(f"/api/boards/{a}", headers=AS(admin_id))
    one_each = n["q"]
    for t in near:
        _set(client, t, c["id"], far[:8], admin_id)
    n["q"] = 0
    client.get(f"/api/boards/{a}", headers=AS(admin_id))
    four_each = n["q"]
    event.remove(cityos_main.engine, "before_cursor_execute", h)
    assert four_each <= one_each + 2, \
        f"{one_each} queries for 20 links, {four_each} for 80 — loading scales with them"


def test_01c_two_way_needs_admin_on_the_target_board(client, admin_id, guinea_id):
    """A two-way column CREATES a column on the target board. Writing into
    someone else's board takes rights on that board — refused out loud rather
    than quietly downgraded to one-way."""
    a, b = _board(client, admin_id, "מקור a1c"), _board(client, admin_id, "יעד a1c")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    client.post(f"/api/boards/{b}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})   # not admin
    r, col = _connect(client, guinea_id, a, [b], two_way=True)
    assert r.status_code == 403 and "מנהל לוח" in r.text
    assert col is None
    # one-way into the same board is fine — nothing is written there
    r2, col2 = _connect(client, guinea_id, a, [b], two_way=False, title="חד")
    assert r2.status_code == 200 and col2 is not None


def test_01d_a_workspace_admin_is_unrestricted(client, admin_id):
    a, b = _board(client, admin_id, "מקור a1d"), _board(client, admin_id, "יעד a1d")
    r, col = _connect(client, admin_id, a, [b], two_way=True)
    assert r.status_code == 200 and col["connect"]["two_way"] is True


def test_01e_an_editor_still_cannot_add_columns_at_all(client, admin_id, member_id):
    a, b = _board(client, admin_id, "מקור a1e"), _board(client, admin_id, "יעד a1e")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    r, _ = _connect(client, member_id, a, [b])
    assert r.status_code == 403
