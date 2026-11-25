"""A group's header under a filter counts the whole answer, not the page.

On a board past the paging threshold the browser asks POST
/api/boards/{id}/items/query for its rows fifty at a time. Under a filter the
header of each group used to count the rows that had arrived, so a group that
held 78 matches read 50 — or 20, when the groups above it had used up most of
the first page — and nothing on the screen said the rest existed. monday
showed 78.

The answer now carries `group_matched`: {"<group_id>": n, ..., "null": n}, the
number of top-level rows that answered the cut in each group, over the whole
answer. Pinned here:

* it does not depend on `limit` or `offset` — a page is a window onto the
  answer, and the count is about the answer;
* it adds up to `matched`, so the headers and the toolbar never disagree;
* a free-text `q` narrows it exactly as it narrows the rows;
* every group of the board is a key, and a group nothing matched in reads 0
  (not absent — the browser would fall back to counting loaded rows);
* a parent that is there only as context for a matching sub-item is counted,
  because it is a row the header sits over;
* "null" appears only when some matching row has no group on this board;
* a reader who may not see an item does not have it counted — a count is a
  leak of the rows the permission hides just as surely as the rows are.
"""
import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from conftest import join_primary_env


def AS(uid):
    return {"X-CityOS-User": str(uid)}


def _query(client, uid, bid, **body):
    r = client.post(f"/api/boards/{bid}/items/query", headers=AS(uid),
                    json={"limit": 50, "offset": 0, **body})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, admin_id, bid, gid, title, **extra):
    r = client.post("/api/tasks", headers=AS(admin_id),
                    json={"board_id": bid, "group_id": gid, "title": title, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _wipe_items(bid):
    with Session(cityos_main.engine) as db:
        db.query(cityos_main.Task).filter(cityos_main.Task.board_id == bid)\
          .delete(synchronize_session=False)
        db.commit()


@pytest.fixture
def reader(client, admin_id):
    email = "test.group.matched.reader@cityos.test"
    for u in client.get("/api/users", headers=AS(admin_id)).json():
        if u.get("email") == email:
            uid = u["id"]
            break
    else:
        r = client.post("/api/users", headers=AS(admin_id),
                        json={"name": "קוראת ספירת קבוצות", "email": email, "role": "member"})
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
    join_primary_env(client, uid)
    return uid


@pytest.fixture
def board(client, admin_id):
    """Three groups: A holds 4 «תפוח» + 2 «בננה», B holds 3 «תפוח», C holds
    only «בננה». So a «תפוח» search matches 7 rows over two groups and none
    in C."""
    r = client.post("/api/boards", headers=AS(admin_id), json={"name": "ספירת קבוצות"})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        # a new board opens with starter items; this test counts rows
        _wipe_items(bid)
        for name in ("ב", "ג"):
            r = client.post("/api/groups", headers=AS(admin_id),
                            json={"board_id": bid, "name": name})
            assert r.status_code == 200, r.text
        gids = [g["id"] for g in
                client.get(f"/api/boards/{bid}", headers=AS(admin_id)).json()["groups"]]
        assert len(gids) >= 3, gids
        a, b, c = gids[0], gids[1], gids[2]
        ids = {"a_apple": [], "b_apple": [], "a_banana": [], "c_banana": []}
        for i in range(4):
            ids["a_apple"].append(_item(client, admin_id, bid, a, f"תפוח א{i}"))
        for i in range(2):
            ids["a_banana"].append(_item(client, admin_id, bid, a, f"בננה א{i}"))
        for i in range(3):
            ids["b_apple"].append(_item(client, admin_id, bid, b, f"תפוח ב{i}"))
        ids["c_banana"].append(_item(client, admin_id, bid, c, "בננה ג0"))
        yield {"id": bid, "gids": gids, "a": a, "b": b, "c": c, **ids}
    finally:
        _wipe_items(bid)
        client.delete(f"/api/boards/{bid}", headers=AS(admin_id))


def test_a_small_page_still_reports_every_groups_full_count(client, admin_id, board):
    res = _query(client, admin_id, board["id"], q="תפוח", limit=5)
    assert len(res["items"]) == 5, res["items"]
    assert res["matched"] == 7, res["matched"]
    gm = res["group_matched"]
    assert gm[str(board["a"])] == 4, gm
    assert gm[str(board["b"])] == 3, gm
    assert sum(gm.values()) == res["matched"], gm


def test_the_offset_of_the_page_does_not_change_the_counts(client, admin_id, board):
    pages = [_query(client, admin_id, board["id"], q="תפוח", limit=3, offset=off)
             for off in (0, 3, 6)]
    first = pages[0]["group_matched"]
    for p in pages[1:]:
        assert p["group_matched"] == first, (p["group_matched"], first)
    # and the pages, laid end to end, really are the rows that were counted
    seen = [t["id"] for p in pages for t in p["items"]]
    assert sorted(seen) == sorted(board["a_apple"] + board["b_apple"]), seen


def test_a_search_narrows_each_groups_count(client, admin_id, board):
    everything = _query(client, admin_id, board["id"])["group_matched"]
    assert everything[str(board["a"])] == 6, everything
    assert everything[str(board["b"])] == 3, everything
    assert everything[str(board["c"])] == 1, everything

    bananas = _query(client, admin_id, board["id"], q="בננה")
    gm = bananas["group_matched"]
    assert gm[str(board["a"])] == 2, gm
    assert gm[str(board["b"])] == 0, gm
    assert gm[str(board["c"])] == 1, gm
    assert sum(gm.values()) == bananas["matched"] == 3, (gm, bananas["matched"])


def test_a_group_nothing_matched_in_reads_zero_rather_than_missing(client, admin_id, board):
    gm = _query(client, admin_id, board["id"], q="תפוח")["group_matched"]
    for gid in board["gids"]:
        assert str(gid) in gm, (gid, gm)
    assert gm[str(board["c"])] == 0, gm
    # nothing on this board is ungrouped, so there is no "ללא קבוצה" bucket
    assert "null" not in gm, gm

    # a search nothing answers still names every group, all at zero
    none = _query(client, admin_id, board["id"], q="אין-כזה-דבר-בכלל")
    assert none["matched"] == 0, none
    assert none["group_matched"] == {str(g): 0 for g in board["gids"]}, none["group_matched"]


def test_a_parent_shown_only_for_its_matching_sub_item_is_counted_in_its_group(
        client, admin_id, board):
    parent = board["c_banana"][0]
    _item(client, admin_id, board["id"], board["c"], "תפוח מתחת לבננה", parent_id=parent)
    res = _query(client, admin_id, board["id"], q="תפוח")
    gm = res["group_matched"]
    # the banana parent did not match; it is on screen to say where the sub is
    assert gm[str(board["c"])] == 1, gm
    assert res["matched_context"] == 1, res
    assert sum(gm.values()) == res["matched"] == 8, (gm, res["matched"])


def test_a_row_with_no_group_on_the_board_is_counted_under_null(client, admin_id, board):
    moved = board["b_apple"][0]
    with Session(cityos_main.engine) as db:
        t = db.get(cityos_main.Task, moved)
        orig = t.group_id
        t.group_id = None
        db.commit()
    try:
        res = _query(client, admin_id, board["id"], q="תפוח", limit=2)
        gm = res["group_matched"]
        assert gm.get("null") == 1, gm
        assert gm[str(board["b"])] == 2, gm
        assert sum(gm.values()) == res["matched"] == 7, (gm, res["matched"])
    finally:
        with Session(cityos_main.engine) as db:
            db.get(cityos_main.Task, moved).group_id = orig
            db.commit()


def test_a_reader_is_not_counted_items_they_may_not_see(client, admin_id, board, reader):
    bid = board["id"]
    r = client.post(f"/api/boards/{bid}/members", headers=AS(admin_id),
                    json={"user_id": reader, "role": "assigned_only"})
    assert r.status_code == 200, r.text
    mine = [board["a_apple"][0], board["b_apple"][0], board["b_apple"][1]]
    for tid in mine:
        r = client.post(f"/api/tasks/{tid}/assignees", headers=AS(admin_id),
                        json={"user_id": reader, "action": "add"})
        assert r.status_code == 200, r.text

    res = _query(client, reader, bid, q="תפוח", limit=1)
    gm = res["group_matched"]
    assert res["matched"] == 3, res
    assert gm[str(board["a"])] == 1, gm
    assert gm[str(board["b"])] == 2, gm
    assert gm[str(board["c"])] == 0, gm
    assert sum(gm.values()) == res["matched"], gm

    # and the admin, on the same board and the same question, still sees all 7
    full = _query(client, admin_id, bid, q="תפוח", limit=1)["group_matched"]
    assert full[str(board["a"])] == 4 and full[str(board["b"])] == 3, full
