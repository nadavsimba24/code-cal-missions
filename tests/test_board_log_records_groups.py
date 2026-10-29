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
