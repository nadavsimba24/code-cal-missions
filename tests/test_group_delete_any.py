"""כל קבוצה ניתנת למחיקה — גם "בתכנון", גם הראשונה, גם כשיש בה פריטים.

A board ships with three groups, and none of them is load-bearing once the board
exists: the first one, the one named "בתכנון", and the one carrying the backlog
status are all just groups. Nothing may hold one back, and an item in a deleted
group is detached rather than deleted — it falls to "ללא קבוצה", where it is
still on the board and still findable.

This is a guard against the rule growing back. The reason it is worth writing
down is that the board's own defaults look privileged from the outside — a new
item is filed into "בתכנון" by default, and status automations name groups — so
"the first group cannot be removed" is an easy thing to add by accident.
"""


def _board(client, name="לוח מחיקות"):
    return client.post("/api/boards", json={"name": name}).json()["id"]


def _groups(client, bid):
    return client.get(f"/api/boards/{bid}").json()["groups"]


def test_a_new_board_ships_with_three_groups_and_none_is_special(client):
    bid = _board(client)
    names = [g["name"] for g in _groups(client, bid)]
    assert names == ["בתכנון", "בביצוע", "הושלם"]


def test_the_backlog_group_can_be_deleted(client):
    bid = _board(client)
    g = next(x for x in _groups(client, bid) if x["name"] == "בתכנון")
    assert g["position"] == 0 and g["task_status"] == "backlog"   # first, and the default one

    r = client.delete(f"/api/groups/{g['id']}")
    assert r.status_code == 200, r.text
    assert [x["name"] for x in _groups(client, bid)] == ["בביצוע", "הושלם"]


def test_every_group_on_a_board_can_go_including_the_last_one(client):
    bid = _board(client)
    for g in _groups(client, bid):
        assert client.delete(f"/api/groups/{g['id']}").status_code == 200, g["name"]
    assert _groups(client, bid) == []


def test_the_items_in_a_deleted_group_are_detached_not_deleted(client):
    bid = _board(client)
    g = next(x for x in _groups(client, bid) if x["name"] == "בתכנון")
    kept = [client.post("/api/tasks", json={"board_id": bid, "group_id": g["id"],
                                            "title": f"פריט {i}"}).json()["id"]
            for i in range(3)]

    assert client.delete(f"/api/groups/{g['id']}").status_code == 200

    board = client.get(f"/api/boards/{bid}").json()
    survivors = {t["id"]: t for t in board["tasks"]}
    for tid in kept:
        assert tid in survivors, "an item was deleted along with its group"
        assert survivors[tid]["group_id"] is None   # → the "ללא קבוצה" bucket


def test_deleting_a_group_that_is_already_gone_says_so(client):
    """The reason a refusal carries matters: the client shows it verbatim now."""
    bid = _board(client)
    g = _groups(client, bid)[0]
    assert client.delete(f"/api/groups/{g['id']}").status_code == 200
    r = client.delete(f"/api/groups/{g['id']}")
    assert r.status_code == 404
    assert r.json()["detail"] == "group not found"
