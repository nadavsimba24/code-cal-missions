"""A page of a paged board fills one group before it starts the next.

An item's position is counted inside its group — every group starts again at
0 — and /items/query used to order the board by position alone. That
interleaved the groups: position 0 of every group, then position 1 of every
group. Past the paging threshold that order is what gets cut into pages, so
page one held a row or two of each group while every header printed the
group's true size (group_counts) — "the header says 300 and there are four
rows", items that looked missing because they were still further down the
stream.

Pinned here: without a sort the rows come back group by group in the board's
own group order, and by position inside each group — so the first page is the
top of the first group, exactly what the screen draws first.
"""
import pytest
from sqlalchemy.orm import Session

import main as cityos_main


def AS(uid):
    return {"X-CityOS-User": str(uid)}


@pytest.fixture
def board(client, admin_id):
    r = client.post("/api/boards", headers=AS(admin_id), json={"name": "סדר עמודים"})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        # a new board opens with starter items; this test counts rows
        with Session(cityos_main.engine) as db:
            db.query(cityos_main.Task).filter(cityos_main.Task.board_id == bid)\
              .delete(synchronize_session=False)
            db.commit()
        yield bid
    finally:
        with Session(cityos_main.engine) as db:
            db.query(cityos_main.Task).filter(cityos_main.Task.board_id == bid)\
              .delete(synchronize_session=False)
            db.commit()
        client.delete(f"/api/boards/{bid}", headers=AS(admin_id))


def _query(client, uid, bid, **body):
    r = client.post(f"/api/boards/{bid}/items/query", headers=AS(uid),
                    json={"limit": 50, "offset": 0, **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_unsorted_rows_come_back_group_by_group_not_interleaved(client, admin_id, board):
    for name in ("ב", "ג"):
        r = client.post("/api/groups", headers=AS(admin_id),
                        json={"board_id": board, "name": name})
        assert r.status_code == 200, r.text
    groups = client.get(f"/api/boards/{board}", headers=AS(admin_id)).json()["groups"]
    gids = [g["id"] for g in groups]
    assert len(gids) >= 3
    # created round-robin, so position 0 exists in every group, then 1, then 2 —
    # the shape a board-wide ORDER BY position interleaves
    for i in range(3):
        for gid in gids:
            r = client.post("/api/tasks", headers=AS(admin_id),
                            json={"board_id": board, "group_id": gid, "title": f"{gid}-{i}"})
            assert r.status_code == 200, r.text

    rows = _query(client, admin_id, board)["items"]
    got = [t["group_id"] for t in rows]
    want = [gid for gid in gids for _ in range(3)]
    assert got == want, f"rows arrived interleaved across groups: {got}"
    # and inside a group, in the group's own order
    first = [t["title"] for t in rows if t["group_id"] == gids[0]]
    assert first == [f"{gids[0]}-{i}" for i in range(3)], first

    # the first page of a small page size is the top of the first group only
    page = _query(client, admin_id, board, limit=3)["items"]
    assert {t["group_id"] for t in page} == {gids[0]}, page
