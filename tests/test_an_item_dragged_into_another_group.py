"""An item dragged from one group into another lands exactly where it was let go.

Items used to be dragged only within their own group; moving one to another
group was the item menu's or the bulk bar's job. Dragging across groups is
allowed now, and the board sends the same two things a drag inside a group
sends: the target group, and the item it should follow. Pinned here:

- it lands after that item, or at the top when it follows none, and both
  groups stay a dense run of positions — the gap behind it is closed;
- its status is not touched, because a drag says where an item sits, not what
  was decided about it;
- the group id is checked. It used to be written as sent, so a number naming
  another board's group filed the item there, out of sight of its own board.

The frontend half — the landing indicator and no text selection — is pinned
in tests/frontend/item_drag_feedback.mjs.
"""
import pytest


def _board(client, name, groups=("א", "ב")):
    b = client.post("/api/boards", json={"name": name, "workspace_id": 1}).json()
    gids = [client.post("/api/groups", json={"board_id": b["id"], "name": g}).json()["id"]
            for g in groups]
    return b["id"], gids


def _tasks(client, bid):
    return client.get(f"/api/boards/{bid}").json()["tasks"]


def _order(client, bid, gid):
    ts = sorted((t for t in _tasks(client, bid) if t.get("group_id") == gid),
                key=lambda t: t["position"])
    return [t["title"] for t in ts], [t["position"] for t in ts]


@pytest.fixture
def boards(client):
    made = []
    def make(name, groups=("א", "ב")):
        bid, gids = _board(client, name, groups)
        made.append(bid)
        return bid, gids
    try:
        yield make
    finally:
        for bid in made:
            client.delete(f"/api/boards/{bid}")


def _add(client, bid, gid, title):
    return client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                           "title": title}).json()["id"]


def test_it_lands_after_the_item_it_was_dropped_below(client, boards):
    bid, (ga, gb) = boards("drag-after")
    a1 = _add(client, bid, ga, "a1"); _add(client, bid, ga, "a2")
    b1 = _add(client, bid, gb, "b1"); _add(client, bid, gb, "b2")
    r = client.post(f"/api/tasks/{a1}/move", json={"group_id": gb, "after_id": b1})
    assert r.status_code == 200, r.text
    assert _order(client, bid, gb) == (["b1", "a1", "b2"], [0, 1, 2])
    # the group it left closes the gap behind it
    assert _order(client, bid, ga) == (["a2"], [0])


def test_following_nothing_means_the_top_of_the_new_group(client, boards):
    bid, (ga, gb) = boards("drag-top")
    a1 = _add(client, bid, ga, "a1")
    _add(client, bid, gb, "b1"); _add(client, bid, gb, "b2")
    client.post(f"/api/tasks/{a1}/move", json={"group_id": gb, "after_id": None})
    assert _order(client, bid, gb) == (["a1", "b1", "b2"], [0, 1, 2])


def test_an_empty_group_takes_the_item(client, boards):
    bid, (ga, gb) = boards("drag-empty")
    a1 = _add(client, bid, ga, "a1")
    client.post(f"/api/tasks/{a1}/move", json={"group_id": gb, "after_id": None})
    assert _order(client, bid, gb) == (["a1"], [0])
    assert _order(client, bid, ga) == ([], [])


def test_the_item_keeps_its_status_in_its_new_group(client, boards):
    bid, (ga, gb) = boards("drag-status")
    a1 = _add(client, bid, ga, "a1")
    client.patch(f"/api/tasks/{a1}", json={"status": "done"})
    before = next(t for t in _tasks(client, bid) if t["id"] == a1)["status"]
    client.post(f"/api/tasks/{a1}/move", json={"group_id": gb, "after_id": None})
    t = next(t for t in _tasks(client, bid) if t["id"] == a1)
    assert t["group_id"] == gb and t["status"] == before


def test_another_boards_group_is_refused_and_nothing_moves(client, boards):
    bid, (ga, _gb) = boards("drag-home")
    _other, (gx, _gy) = boards("drag-elsewhere")
    a1 = _add(client, bid, ga, "a1")
    r = client.post(f"/api/tasks/{a1}/move", json={"group_id": gx, "after_id": None})
    assert r.status_code == 404, r.text
    assert next(t for t in _tasks(client, bid) if t["id"] == a1)["group_id"] == ga


def test_a_group_that_does_not_exist_is_not_found(client, boards):
    bid, (ga, _gb) = boards("drag-ghost")
    a1 = _add(client, bid, ga, "a1")
    assert client.post(f"/api/tasks/{a1}/move",
                       json={"group_id": 999999999, "after_id": None}).status_code == 404


def test_a_group_id_that_is_not_a_number_is_a_bad_request(client, boards):
    bid, (ga, _gb) = boards("drag-junk")
    a1 = _add(client, bid, ga, "a1")
    assert client.post(f"/api/tasks/{a1}/move",
                       json={"group_id": "abc", "after_id": None}).status_code == 400


def test_no_group_is_still_a_place_an_item_can_be_put(client, boards):
    bid, (ga, _gb) = boards("drag-none")
    a1 = _add(client, bid, ga, "a1")
    r = client.post(f"/api/tasks/{a1}/move", json={"group_id": None})
    assert r.status_code == 200, r.text
    assert next(t for t in _tasks(client, bid) if t["id"] == a1)["group_id"] is None
