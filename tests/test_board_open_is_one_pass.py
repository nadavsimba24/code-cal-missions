"""Opening a board must cost a fixed number of queries, not one per item.

Serializing an item asked the database four separate questions — its assignees,
its sub-item count, its comment count, and its sub-items — so a board cost
about ten statements per row. Against SQLite, in-process, that is invisible:
the suite never noticed. Against QA's Postgres every statement is a network
round trip, and a real board took twenty seconds to open.

So the thing to pin is not the wall clock on this machine, which proves
nothing. It is the statement count, and specifically that **it does not grow
with the number of items** — the property that was broken. The second test
doubles the board and demands the count stay put.

The third is the safety net: the batched answers have to be the SAME answers.
It compares every item of a prefetched board read against the identical item
serialized through the fallback path, field by field.
"""
import pytest
from sqlalchemy import event

import main as cityos_main


@pytest.fixture
def counted():
    """Count SQL statements issued while the block runs."""
    class Counter:
        n = 0

    c = Counter()

    def _tick(*a, **kw):
        c.n += 1

    event.listen(cityos_main.engine, "before_cursor_execute", _tick)
    try:
        yield c
    finally:
        event.remove(cityos_main.engine, "before_cursor_execute", _tick)


def _board_with(client, admin_id, name, n_items, n_subs=2, people=()):
    """A board carrying n_items rows, each with sub-items, a comment and an
    assignee — the shape that made the old code issue ten queries a row.

    Returns (board_id, ids). A new board is born with three starter items, so
    the ids are what the caller must look at; the board holds n_items + 3.
    """
    bid = client.post("/api/boards", json={"actor_id": admin_id, "name": name}).json()["id"]
    gid = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["groups"][0]["id"]
    ids = []
    for i in range(n_items):
        tid = client.post("/api/tasks", json={
            "actor_id": admin_id, "board_id": bid, "group_id": gid,
            "title": f"שורה {i}", "status": "in_progress", "priority": "medium",
        }).json()["id"]
        ids.append(tid)
        if people:
            client.post(f"/api/tasks/{tid}/assignees",
                        json={"actor_id": admin_id, "user_ids": [people[i % len(people)]]})
        client.post(f"/api/tasks/{tid}/comments",
                    json={"actor_id": admin_id, "content": "הערה"})
        for s in range(n_subs):
            client.post("/api/tasks", json={
                "actor_id": admin_id, "board_id": bid, "group_id": gid,
                "parent_id": tid, "title": f"תת {i}.{s}",
            })
    return bid, ids


def test_a_board_opens_in_a_fixed_number_of_queries(client, admin_id, member_id,
                                                    guinea_id, counted):
    bid, ids = _board_with(client, admin_id, "ביצועים א", 25,
                           people=(member_id, guinea_id))
    client.get(f"/api/boards/{bid}?user_id={admin_id}")      # warm anything cached per process

    counted.n = 0
    r = client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["tasks"]) == 25 + 3        # + the starter items
    assert sum(len(t["subtasks"]) for t in body["tasks"]) == 50

    # 75 serialized items. Ten queries each was 750; the batched read is a
    # couple of dozen. The bound is deliberately loose — what matters is that
    # it is nowhere near per-item, and the next test is the real guard.
    assert counted.n < 60, (
        f"opening a 25-item board took {counted.n} queries — "
        "something went back to asking per item")


def test_doubling_the_items_does_not_double_the_queries(client, admin_id,
                                                        member_id, counted):
    """The property that was actually broken: cost per item.

    A board twice the size may read more rows, but it must not issue
    materially more statements. Anything that grows here is an N+1 creeping
    back in, and on Postgres it is paid in round trips.
    """
    small, _ = _board_with(client, admin_id, "ביצועים קטן", 10, people=(member_id,))
    big, _ = _board_with(client, admin_id, "ביצועים גדול", 40, people=(member_id,))
    for b in (small, big):
        client.get(f"/api/boards/{b}?user_id={admin_id}")

    counted.n = 0
    client.get(f"/api/boards/{small}?user_id={admin_id}")
    n_small = counted.n

    counted.n = 0
    client.get(f"/api/boards/{big}?user_id={admin_id}")
    n_big = counted.n

    assert n_big - n_small <= 6, (
        f"10 items cost {n_small} queries and 40 items cost {n_big} — "
        "the cost is still following the item count")


def test_the_batched_answers_are_the_same_answers(client, admin_id, member_id,
                                                  guinea_id):
    """A faster read is worthless if it reads something else.

    The board endpoint warms the per-session caches; _serialize_task in a fresh
    session finds nothing warmed and falls back to its own queries. Both must
    produce the identical item.
    """
    bid, ids = _board_with(client, admin_id, "ביצועים זהות", 6,
                           people=(member_id, guinea_id))
    fast = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    fast_rows = [t for t in fast["tasks"] if t["id"] in ids]

    with cityos_main.Session(cityos_main.engine) as db:
        board = db.query(cityos_main.Board).filter(cityos_main.Board.id == bid).first()
        cols = (board.settings or {}).get("columns", [])
        rows = (db.query(cityos_main.Task)
                  .filter(cityos_main.Task.board_id == bid,
                          cityos_main.Task.is_archived == False,          # noqa: E712
                          cityos_main.Task.parent_id == None)             # noqa: E711
                  .order_by(cityos_main.Task.position).all())
        slow = [cityos_main._serialize_task(t, db, user_id=admin_id,
                                            board_role="admin", columns=cols)
                for t in rows if t.id in ids]

    assert len(fast_rows) == len(slow) == 6
    for a, b in zip(fast_rows, slow):
        assert a["id"] == b["id"]
        assert a["assignees"] == [{"id": u["id"], "name": u["name"],
                                   "avatar_url": u["avatar_url"]} for u in b["assignees"]]
        assert a["subtask_count"] == b["subtask_count"] == 2
        assert a["comment_count"] == b["comment_count"] == 1
        assert [s["id"] for s in a["subtasks"]] == [s["id"] for s in b["subtasks"]]
        assert [s["assignees"] for s in a["subtasks"]] == [s["assignees"] for s in b["subtasks"]]
        assert a["custom_fields"] == b["custom_fields"]
        # col_perms is no longer per item — the board states it once
        assert "col_perms" not in a and "col_perms" not in b
        assert a["my_perm"] == b["my_perm"]


def test_a_columns_permission_is_stated_once_for_the_board(client, admin_id, guinea_id):
    """It depends on the column and the viewer's role, never on the item.

    It used to ride on every item anyway — on a board of 687 items and 29
    columns, twenty thousand copies of the same map, and over half the
    response. The board states it once. What stays per item is the
    consequence: a value the viewer may not see is simply not there.
    """
    bid, ids = _board_with(client, admin_id, "הרשאות עמודה", 3)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    # give the board a column, write a value into it, then restrict it
    cols = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
    cid = "col_secret"
    r = client.patch(f"/api/boards/{bid}",
                     json={"actor_id": admin_id,
                           "columns": cols + [{"id": cid, "type": "text", "title": "סודי"}]})
    assert r.status_code == 200, r.text
    assert any(c["id"] == cid for c in r.json()["columns"]), r.text
    client.patch(f"/api/tasks/{ids[0]}",
                 json={"actor_id": admin_id, "custom_fields": {cid: "לעיניי מנהל"}})

    # the admin sees the column as editable, stated once on the board
    seen = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    assert seen["col_perms"].get(cid) == "edit"
    assert all("col_perms" not in t for t in seen["tasks"])

    # restrict it for the other member: view only
    client.post(f"/api/boards/{bid}/columns/{cid}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "view"})
    theirs = client.get(f"/api/boards/{bid}?user_id={guinea_id}").json()
    assert theirs["col_perms"].get(cid) == "view"
    row = next(t for t in theirs["tasks"] if t["id"] == ids[0])
    assert row["custom_fields"].get(cid) == "לעיניי מנהל", "view means they can read it"

    # now hide it from them entirely — the value must not be in the response
    client.post(f"/api/boards/{bid}/columns/{cid}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"})
    theirs = client.get(f"/api/boards/{bid}?user_id={guinea_id}").json()
    assert theirs["col_perms"].get(cid) == "none"
    row = next(t for t in theirs["tasks"] if t["id"] == ids[0])
    assert cid not in row["custom_fields"], "a column they may not see still carried its value"
    # and the admin is unaffected
    mine = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    assert next(t for t in mine["tasks"]
                if t["id"] == ids[0])["custom_fields"].get(cid) == "לעיניי מנהל"
