"""הלוג מתעד קבוצות: יצירה, מחיקה, ומעבר רשומה ביניהן.

Three events that left no trace anywhere.

Creating and deleting a group are board events, the same kind as the column
work: a group is a shelf the board has, and until now nobody could say who
added or removed one, or when. Moving an item between groups is an item
event — and the odd one out, because the drag already fired its automation
trigger and already audited any status change beside it, while the move
itself recorded nothing. On a board where the group IS the workflow, the one
thing worth reading was the one thing missing from both logs.

What is pinned here is the whole path: the rows exist, they carry group NAMES
rather than ids, the deleted group's name survives its own deletion, and a
move made by an automation is attributed to the rule rather than to a person.
The wording half — which sentence each of the three gets — is pinned by
tests/frontend/group_log_line.mjs.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "group_log_line.mjs"


def _board(client, admin_id, name="לוח קבוצות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _group(client, bid, admin_id, name):
    r = client.post("/api/groups", json={"board_id": bid, "name": name, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _board_log(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/activity?user_id={admin_id}").json()["activity"]


def _item_log(client, tid, admin_id):
    return client.get(f"/api/tasks/{tid}/activity?user_id={admin_id}").json()["activity"]


def _rows(log, action, field="group"):
    return [r for r in log if r.get("field") == field and r.get("action") == action]


def test_creating_a_group_is_written_to_the_board_log(client, admin_id):
    bid = _board(client, admin_id)
    try:
        _group(client, bid, admin_id, "תכנון")
        made = _rows(_board_log(client, bid, admin_id), "create")
        assert len(made) == 1, made
        assert made[0]["new"] == "תכנון"
        # a board event, so it hangs off the board and not off an item
        assert made[0]["task_id"] is None
        assert made[0]["user_id"] == admin_id
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_a_deleted_group_leaves_its_name_behind(client, admin_id):
    """The row is the only place the name survives — the group itself is gone,
    and the items it held fall back to "ללא קבוצה" rather than being deleted."""
    bid = _board(client, admin_id)
    try:
        gid = _group(client, bid, admin_id, "לביטול")
        r = client.delete(f"/api/groups/{gid}?user_id={admin_id}")
        assert r.status_code == 200, r.text
        gone = _rows(_board_log(client, bid, admin_id), "delete")
        assert len(gone) == 1, gone
        assert gone[0]["old"] == "לביטול", "the name did not survive its group"
        assert gone[0]["task_id"] is None
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_moving_an_item_between_groups_is_written_to_both_logs(client, admin_id):
    bid = _board(client, admin_id)
    try:
        g1 = _group(client, bid, admin_id, "תכנון")
        g2 = _group(client, bid, admin_id, "בביצוע")
        tid = client.post("/api/tasks", json={"board_id": bid, "group_id": g1,
                                              "title": "רשומה",
                                              "user_id": admin_id}).json()["id"]
        r = client.post(f"/api/tasks/{tid}/move", json={"group_id": g2, "actor_id": admin_id})
        assert r.status_code == 200, r.text

        moved = _rows(_item_log(client, tid, admin_id), "update")
        assert len(moved) == 1, moved
        # names, not ids: an id would point at nothing once the group is
        # deleted, or at whatever group is created into that id next
        assert (moved[0]["old"], moved[0]["new"]) == ("תכנון", "בביצוע"), moved[0]

        # the board's log shows its items' events, so it is there too
        assert any(r["field"] == "group" and r["action"] == "update"
                   for r in _board_log(client, bid, admin_id))
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_every_way_to_move_an_item_writes_a_line(client, admin_id):
    """Four paths change an item's group, and the log must not depend on
    which one somebody used.

    The menu sends group_id with a position, a drag sends it with an anchor,
    a plain move sends neither, and a selection goes to a bulk endpoint of
    its own. That last one changed the group and fired its automations and
    recorded nothing — so selecting rows and moving them left no trace, while
    doing the identical thing one row at a time did. A log with a hole in the
    shape of one gesture is worse than no log: it reads as "this never
    happened" rather than as "this is not recorded".
    """
    bid = _board(client, admin_id)
    try:
        g1 = _group(client, bid, admin_id, "א")
        g2 = _group(client, bid, admin_id, "ב")

        def item(title):
            return client.post("/api/tasks", json={"board_id": bid, "group_id": g1,
                                                   "title": title,
                                                   "user_id": admin_id}).json()["id"]

        menu, drag, plain, bulk = (item("תפריט"), item("גרירה"),
                                   item("פשוט"), item("מרובה"))
        client.post(f"/api/tasks/{menu}/move",
                    json={"group_id": g2, "position": 0, "actor_id": admin_id})
        client.post(f"/api/tasks/{drag}/move",
                    json={"group_id": g2, "after_id": None, "actor_id": admin_id})
        client.post(f"/api/tasks/{plain}/move",
                    json={"group_id": g2, "actor_id": admin_id})
        r = client.post(f"/api/boards/{bid}/items/move",
                        json={"ids": [bulk], "group_id": g2, "actor_id": admin_id})
        assert r.status_code == 200, r.text

        moves = _rows(_board_log(client, bid, admin_id), "update")
        moved = {m["task_title"]: (m["old"], m["new"]) for m in moves}
        assert set(moved) == {"תפריט", "גרירה", "פשוט", "מרובה"}, moved
        for title, (old, new) in moved.items():
            assert (old, new) == ("א", "ב"), (title, old, new)
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_a_selection_of_several_gets_a_line_each(client, admin_id):
    """One gesture over many items is still one event per item — the log is
    read per item, and a single row for five of them could not say which."""
    bid = _board(client, admin_id)
    try:
        g1 = _group(client, bid, admin_id, "מקור")
        g2 = _group(client, bid, admin_id, "יעד")
        ids = [client.post("/api/tasks", json={"board_id": bid, "group_id": g1,
                                               "title": f"פריט {i}",
                                               "user_id": admin_id}).json()["id"]
               for i in range(3)]
        client.post(f"/api/boards/{bid}/items/move",
                    json={"ids": ids, "group_id": g2, "actor_id": admin_id})
        moves = _rows(_board_log(client, bid, admin_id), "update")
        assert len(moves) == 3, moves
        assert {m["task_title"] for m in moves} == {"פריט 0", "פריט 1", "פריט 2"}

        # an item already in the target is not moved, so it is not an event
        client.post(f"/api/boards/{bid}/items/move",
                    json={"ids": ids, "group_id": g2, "actor_id": admin_id})
        assert len(_rows(_board_log(client, bid, admin_id), "update")) == 3
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_a_drag_that_lands_where_it_started_is_not_an_event(client, admin_id):
    """Only a real move. A log that records non-moves is a log nobody reads."""
    bid = _board(client, admin_id)
    try:
        g1 = _group(client, bid, admin_id, "תכנון")
        tid = client.post("/api/tasks", json={"board_id": bid, "group_id": g1,
                                              "title": "רשומה",
                                              "user_id": admin_id}).json()["id"]
        client.post(f"/api/tasks/{tid}/move", json={"group_id": g1, "actor_id": admin_id})
        assert _rows(_item_log(client, tid, admin_id), "update") == []
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_three_sentences_are_told_apart():
    """The drawing half — runs the real label functions out of index.html."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
