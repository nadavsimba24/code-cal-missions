"""Duplicating an item, and moving one to another board.

Duplicating copies the connect values as they are — the recommended default,
switchable system-wide with CITYOS_DUPLICATE_ITEM_LINKS=0.

Moving re-homes them: a link is stored against a COLUMN, and column ids do not
survive a move, so the links are carried into the matching column on the target
board and only the ones that column is configured to hold survive.
"""
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


def _connect(client, admin_id, a, b, two_way=True, title="קישור", multiple=True):
    cols = _cols(client, a) + [{"type": "connect", "title": title,
                                "connect": {"board_ids": [b], "multiple": multiple,
                                            "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    return next(x for x in _cols(client, a) if x["type"] == "connect" and x["title"] == title)


def _duplicate(client, admin_id, tid, board_id):
    """What the UI's "שכפול" does: post the item's own cells back as a new item."""
    t = client.get(f"/api/tasks/{tid}", headers=AS(admin_id)).json()
    return client.post("/api/tasks", json={
        "board_id": board_id, "group_id": t.get("group_id"),
        "title": (t.get("title") or "") + " (עותק)",
        "custom_fields": dict(t.get("custom_fields") or {}),
        "user_id": admin_id}).json()["id"]


def _rows(tid):
    with Session(cityos_main.engine) as db:
        return db.query(ItemLink).filter(
            (ItemLink.a_task_id == tid) | (ItemLink.b_task_id == tid)).count()


# ── 14.1 duplicating ────────────────────────────────────────────────────────

def test_duplicating_copies_a_two_way_link(client, admin_id):
    """A two-way value is not a cell at all but a relationship, so posting the
    original's custom_fields did nothing — the copy came out unlinked."""
    a, b = _board(client, admin_id, "מקור d1"), _board(client, admin_id, "יעד d1")
    c = _connect(client, admin_id, a, b)
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    dup = _duplicate(client, admin_id, src, a)
    assert _cell(client, dup, c["id"], admin_id) == [x]
    assert _cell(client, src, c["id"], admin_id) == [x], "duplicating moved the link instead of copying it"


def test_the_far_side_sees_both_after_a_duplicate(client, admin_id):
    a, b = _board(client, admin_id, "מקור d2"), _board(client, admin_id, "יעד d2")
    c = _connect(client, admin_id, a, b)
    mirror = c["connect"]["mirror"][str(b)]
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    dup = _duplicate(client, admin_id, src, a)
    assert sorted(_cell(client, x, mirror, admin_id)) == sorted([src, dup])


def test_duplicating_copies_a_one_way_link(client, admin_id):
    a, b = _board(client, admin_id, "מקור d3"), _board(client, admin_id, "יעד d3")
    c = _connect(client, admin_id, a, b, two_way=False)
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    assert _cell(client, _duplicate(client, admin_id, src, a), c["id"], admin_id) == [x]


def test_the_system_switch_turns_it_off(client, admin_id, monkeypatch):
    monkeypatch.setenv("CITYOS_DUPLICATE_ITEM_LINKS", "0")
    a, b = _board(client, admin_id, "מקור d4"), _board(client, admin_id, "יעד d4")
    c = _connect(client, admin_id, a, b)
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    assert _cell(client, _duplicate(client, admin_id, src, a), c["id"], admin_id) == []
    assert _cell(client, src, c["id"], admin_id) == [x], "the original lost its link"


def test_a_copy_respects_the_column_cardinality(client, admin_id):
    a, b = _board(client, admin_id, "מקור d5"), _board(client, admin_id, "יעד d5")
    c = _connect(client, admin_id, a, b, multiple=False)
    src = _item(client, a, admin_id, "מקור")
    x = _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    assert len(_cell(client, _duplicate(client, admin_id, src, a), c["id"], admin_id)) == 1


def test_creating_an_item_cannot_link_to_what_you_cannot_see(client, admin_id, guinea_id):
    """The create path never had the rules the edit path has, so an item could
    be created already holding links into a board its creator cannot open."""
    a, b = _board(client, admin_id, "מקור d6"), _board(client, admin_id, "סגור d6")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    c = _connect(client, admin_id, a, b, two_way=False)
    x = _item(client, b, admin_id, "סוד")
    nt = client.post("/api/tasks", json={"board_id": a, "title": "חדש",
                                         "custom_fields": {c["id"]: [x]},
                                         "user_id": guinea_id}, headers=AS(guinea_id)).json()
    assert _cell(client, nt["id"], c["id"], admin_id) == []


def test_the_same_holds_for_a_two_way_column_on_create(client, admin_id, guinea_id):
    a, b = _board(client, admin_id, "מקור d7"), _board(client, admin_id, "סגור d7")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    c = _connect(client, admin_id, a, b)
    x = _item(client, b, admin_id, "סוד")
    nt = client.post("/api/tasks", json={"board_id": a, "title": "חדש",
                                         "custom_fields": {c["id"]: [x]},
                                         "user_id": guinea_id}, headers=AS(guinea_id)).json()
    assert _cell(client, nt["id"], c["id"], admin_id) == []


# ── 14.2 moving between boards ──────────────────────────────────────────────

def test_a_matching_column_on_the_target_keeps_the_link(client, admin_id):
    a, a2 = _board(client, admin_id, "מקור m1"), _board(client, admin_id, "מקור2 m1")
    b = _board(client, admin_id, "יעד m1")
    c, c2 = _connect(client, admin_id, a, b), _connect(client, admin_id, a2, b)
    src, x = _item(client, a, admin_id, "נודד"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.post(f"/api/tasks/{src}/move", json={"actor_id": admin_id, "board_id": a2})
    assert _cell(client, src, c2["id"], admin_id) == [x], "the link did not follow into the matching column"
    assert _cell(client, x, c2["connect"]["mirror"][str(b)], admin_id) == [src]


def test_no_such_column_on_the_target_drops_the_link_cleanly(client, admin_id):
    """Not merely 'the cell is empty' — the row has to go, or the far side goes
    on showing a link to an item that is no longer on that board at all."""
    a, a2 = _board(client, admin_id, "מקור m2"), _board(client, admin_id, "מקור2 m2")
    b = _board(client, admin_id, "יעד m2")
    c = _connect(client, admin_id, a, b)
    mirror = c["connect"]["mirror"][str(b)]
    src, x = _item(client, a, admin_id, "נודד"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.post(f"/api/tasks/{src}/move", json={"actor_id": admin_id, "board_id": a2})
    assert _rows(src) == 0
    assert _cell(client, x, mirror, admin_id) == []


def test_a_target_column_pointed_elsewhere_does_not_take_the_link(client, admin_id):
    """Same title, same type — but configured for a different board, so it has
    nowhere to put this relationship."""
    a, a2 = _board(client, admin_id, "מקור m3"), _board(client, admin_id, "מקור2 m3")
    b, b2 = _board(client, admin_id, "יעד m3"), _board(client, admin_id, "יעד2 m3")
    c, c2 = _connect(client, admin_id, a, b), _connect(client, admin_id, a2, b2)
    src, x = _item(client, a, admin_id, "נודד"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.post(f"/api/tasks/{src}/move", json={"actor_id": admin_id, "board_id": a2})
    assert _cell(client, src, c2["id"], admin_id) == []
    assert _rows(src) == 0


def test_only_the_links_the_target_allows_survive(client, admin_id):
    a, a2 = _board(client, admin_id, "מקור m4"), _board(client, admin_id, "מקור2 m4")
    b, b2 = _board(client, admin_id, "יעד m4"), _board(client, admin_id, "יעד2 m4")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b, b2], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in _cols(client, a) if x["type"] == "connect")
    c2 = _connect(client, admin_id, a2, b)          # target column only allows board b
    src = _item(client, a, admin_id, "נודד")
    keep, drop = _item(client, b, admin_id, "נשאר"), _item(client, b2, admin_id, "נופל")
    _set(client, src, c["id"], [keep, drop], admin_id)
    client.post(f"/api/tasks/{src}/move", json={"actor_id": admin_id, "board_id": a2})
    assert _cell(client, src, c2["id"], admin_id) == [keep]


def test_a_dropped_link_is_written_to_the_item_history(client, admin_id):
    """A relationship disappearing during a move is not something to discover
    weeks later."""
    a, a2 = _board(client, admin_id, "מקור m5"), _board(client, admin_id, "מקור2 m5")
    b = _board(client, admin_id, "יעד m5")
    c = _connect(client, admin_id, a, b)
    src, x = _item(client, a, admin_id, "נודד"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.post(f"/api/tasks/{src}/move", json={"actor_id": admin_id, "board_id": a2})
    log = client.get(f"/api/tasks/{src}/activity", headers=AS(admin_id)).json()["activity"]
    assert any(r["field"] == "col:" + c["id"] and r["new"] == "[]" for r in log), \
        "the move dropped a link and said nothing"


def test_a_one_way_column_moves_the_same_way(client, admin_id):
    a, a2 = _board(client, admin_id, "מקור m6"), _board(client, admin_id, "מקור2 m6")
    b = _board(client, admin_id, "יעד m6")
    c = _connect(client, admin_id, a, b, two_way=False)
    c2 = _connect(client, admin_id, a2, b, two_way=False)
    src, x = _item(client, a, admin_id, "נודד"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.post(f"/api/tasks/{src}/move", json={"actor_id": admin_id, "board_id": a2})
    assert _cell(client, src, c2["id"], admin_id) == [x]
    assert _cell(client, src, c["id"], admin_id) == [], "the source board's column key came along"


def test_moving_within_the_same_board_leaves_links_alone(client, admin_id):
    a, b = _board(client, admin_id, "מקור m7"), _board(client, admin_id, "יעד m7")
    c = _connect(client, admin_id, a, b)
    src, x = _item(client, a, admin_id, "נודד"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    groups = client.get(f"/api/boards/{a}").json()["groups"]
    if len(groups) > 1:
        client.post(f"/api/tasks/{src}/move", json={"actor_id": admin_id, "group_id": groups[1]["id"]})
    assert _cell(client, src, c["id"], admin_id) == [x]
