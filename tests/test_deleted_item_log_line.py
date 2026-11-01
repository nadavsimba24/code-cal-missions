"""פריט שנמחק נשאר בלוג הלוח, והשורה שלו מחזירה אותו.

"מחיקת פריט לא מופיעה — זה פשוט מעלים את השורה."

It did, and the deletion was not what removed it. The row was written all
along: delete_task audits it, field "item", with the title in old_value. What
removed it was the log itself — _board_task_ids scopes the log's task rows to
the board's item list, the global hook keeps deleted items off that list, and
so the line recording a deletion was filtered out by the act it recorded.
Every other line of that item's history went with it. From the log's point of
view the item had never existed at all.

Items in the bin count now. A purge takes the audit rows with it, so this
does not accumulate: an item's history is readable for exactly as long as the
item is restorable, and the deletion line carries the way back while it is.

Pinned here: the line appears, the item's whole history survives with it, the
restore offer sits on the deletion line and nowhere else, it is spent once
used, and it is offered only to somebody the restore endpoint would accept.
The drawing — a name that is no longer a button — is pinned by
tests/frontend/deleted_item_log_line.mjs.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "deleted_item_log_line.mjs"


def _board(client, admin_id):
    return client.post("/api/boards", json={"name": "לוח מחיקות",
                                            "user_id": admin_id}).json()["id"]


def _log(client, bid, actor):
    """`user_id` on this endpoint is the person to FILTER BY, not the caller —
    passing the viewer there asks for rows THEY changed, which is empty and
    reads like the feature is broken. The identity goes in the header."""
    r = client.get(f"/api/boards/{bid}/activity",
                   headers={"X-CityOS-User": str(actor)})
    assert r.status_code == 200, r.text
    return r.json()["activity"]


def _delete_row(rows):
    return next((r for r in rows if r["action"] == "delete" and r["field"] == "item"), None)


def test_the_deletion_appears_instead_of_the_item_vanishing(client, admin_id):
    bid = _board(client, admin_id)
    try:
        tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט למחיקה",
                                              "user_id": admin_id}).json()["id"]
        client.patch(f"/api/tasks/{tid}", json={"title": "שם חדש", "user_id": admin_id})
        client.delete(f"/api/tasks/{tid}?user_id={admin_id}")

        rows = _log(client, bid, admin_id)
        gone = _delete_row(rows)
        assert gone is not None, "the deletion left no line in the board log"
        assert gone["old"] == "שם חדש"
        assert gone["task_deleted"] is True
        assert gone["can_restore_item"] is True

        # and the rest of its history came back with it, rather than being
        # erased along with the item
        mine = [r for r in rows if r["task_id"] == tid]
        assert {r["action"] for r in mine} >= {"create", "update", "delete"}, mine
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_offer_is_on_the_deletion_line_and_nowhere_else(client, admin_id):
    bid = _board(client, admin_id)
    try:
        tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                              "user_id": admin_id}).json()["id"]
        client.patch(f"/api/tasks/{tid}", json={"title": "אחר", "user_id": admin_id})
        client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
        offers = [r for r in _log(client, bid, admin_id) if r["can_restore_item"]]
        assert len(offers) == 1 and offers[0]["action"] == "delete", offers
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_restoring_from_the_line_brings_the_item_back(client, admin_id):
    bid = _board(client, admin_id)
    try:
        tid = client.post("/api/tasks", json={"board_id": bid, "title": "חוזר",
                                              "user_id": admin_id}).json()["id"]
        client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
        row = _delete_row(_log(client, bid, admin_id))

        r = client.post(f"/api/tasks/{row['task_id']}/restore", json={"actor_id": admin_id})
        assert r.status_code == 200, r.text
        board = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
        assert any(t["id"] == tid for t in board["tasks"])

        after = next(x for x in _log(client, bid, admin_id) if x["id"] == row["id"])
        assert after["can_restore_item"] is False, "the spent line still offers a restore"
        assert after["task_deleted"] is False, "the line still calls a live item deleted"
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_a_viewer_is_not_offered_what_the_endpoint_would_refuse(client, admin_id, guinea_id):
    """Restoring is a board edit. A viewer may read the log and see that the
    item was deleted — that is history, and it is theirs to read — but the
    button belongs to somebody who could actually use it."""
    bid = _board(client, admin_id)
    try:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
        tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                              "user_id": admin_id}).json()["id"]
        client.delete(f"/api/tasks/{tid}?user_id={admin_id}")

        theirs = _delete_row(_log(client, bid, guinea_id))
        assert theirs is not None, "a viewer cannot see that the item was deleted at all"
        assert theirs["can_restore_item"] is False

        r = client.post(f"/api/tasks/{tid}/restore", json={"actor_id": guinea_id})
        assert r.status_code == 403, r.text
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_line_and_its_button():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
