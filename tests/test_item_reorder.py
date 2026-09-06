"""Group 25 — dragging an item to a new position, and having it stay there.

The drag itself has always worked: pick a row up, drop it, the row lands where
you let go. What did not work was the part that matters — coming back. The move
wrote the dropped item's new position and nothing else, so the group ended up
with two items claiming the same number, and the read path orders by position
alone. The tie went to whichever row the database happened to return first,
which was usually the one that had been there before, and the item sprang back.

These tests are about the order that comes *back* from the server, never about
what the browser did on screen.
"""
import pytest


@pytest.fixture
def group(client):
    """A group of five items of our own, on the demo board."""
    board = client.get("/api/boards/1?user_id=1").json()
    gid = board["groups"][0]["id"] if board.get("groups") else None
    ids = []
    for i in range(5):
        r = client.post("/api/tasks", json={"title": f"reorder-{i}", "board_id": 1, "group_id": gid})
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    yield gid, ids
    for tid in ids:
        client.delete(f"/api/tasks/{tid}")


def _order(client, gid, ids):
    """The board's own order, narrowed to the items this test made."""
    board = client.get("/api/boards/1?user_id=1").json()
    return [t["id"] for t in board["tasks"] if t["id"] in ids and t.get("group_id") == gid]


def test_an_item_dropped_at_the_top_stays_at_the_top(client, group):
    """The report: drag an item up, let go, and it is back where it started."""
    gid, ids = group
    assert _order(client, gid, ids) == ids            # created in order, bottom-first

    r = client.post(f"/api/tasks/{ids[4]}/move", json={"group_id": gid, "position": 0})
    assert r.status_code == 200, r.text
    assert _order(client, gid, ids) == [ids[4], ids[0], ids[1], ids[2], ids[3]]


def _positions(client, gid):
    """Every position in the group — the demo board's own items included."""
    board = client.get("/api/boards/1?user_id=1").json()
    return sorted(t["position"] for t in board["tasks"] if t.get("group_id") == gid)


def test_the_group_keeps_one_item_per_position(client, group):
    """Two items on the same number is what made the order a coin toss."""
    gid, ids = group
    client.post(f"/api/tasks/{ids[3]}/move", json={"group_id": gid, "position": 1})
    pos = _positions(client, gid)
    assert pos == list(range(len(pos))), f"not a dense 0..n-1 sequence: {pos}"


def test_an_item_can_be_dropped_at_the_bottom(client, group):
    gid, ids = group
    client.post(f"/api/tasks/{ids[0]}/move", json={"group_id": gid, "after_id": ids[4]})
    assert _order(client, gid, ids) == [ids[1], ids[2], ids[3], ids[4], ids[0]]


def test_a_position_past_the_end_lands_last_rather_than_failing(client, group):
    """The browser counts rows; a stale count must not throw or leave a hole."""
    gid, ids = group
    r = client.post(f"/api/tasks/{ids[0]}/move", json={"group_id": gid, "position": 99})
    assert r.status_code == 200, r.text
    assert _order(client, gid, ids)[-1] == ids[0]


def test_dropping_after_a_named_item_is_exact(client, group):
    """`after_id` is what the browser sends, because an index counts the wrong
    things: with a filter on, the rows on screen are a subset, and "third row"
    is not "third item"."""
    gid, ids = group
    r = client.post(f"/api/tasks/{ids[0]}/move", json={"group_id": gid, "after_id": ids[3]})
    assert r.status_code == 200, r.text
    assert _order(client, gid, ids) == [ids[1], ids[2], ids[3], ids[0], ids[4]]


def test_dropping_after_nothing_means_the_top(client, group):
    gid, ids = group
    client.post(f"/api/tasks/{ids[2]}/move", json={"group_id": gid, "after_id": None})
    assert _order(client, gid, ids)[0] == ids[2]


def test_an_after_id_from_another_group_is_ignored(client, group):
    """A crafted payload must not thread an item into a group by a stranger."""
    gid, ids = group
    board = client.get("/api/boards/1?user_id=1").json()
    other = next((t["id"] for t in board["tasks"]
                  if t["id"] not in ids and t.get("group_id") != gid), None)
    if other is None:
        pytest.skip("the demo board has no item in another group")
    r = client.post(f"/api/tasks/{ids[0]}/move", json={"group_id": gid, "after_id": other})
    assert r.status_code == 200, r.text
    assert set(_order(client, gid, ids)) == set(ids)   # still all five, still this group


def test_moving_into_another_group_renumbers_both(client, group):
    """The group it left must close the gap, or its next drop lands on a tie."""
    gid, ids = group
    board = client.get("/api/boards/1?user_id=1").json()
    target = next((g["id"] for g in board["groups"] if g["id"] != gid), None)
    if target is None:
        pytest.skip("the demo board has only one group")

    r = client.post(f"/api/tasks/{ids[1]}/move", json={"group_id": target, "position": 0})
    assert r.status_code == 200, r.text

    left = _positions(client, gid)
    assert left == list(range(len(left))), f"gaps left behind: {left}"
    board = client.get("/api/boards/1?user_id=1").json()
    moved = next(t for t in board["tasks"] if t["id"] == ids[1])
    assert moved["group_id"] == target and moved["position"] == 0
