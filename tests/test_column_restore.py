"""שחזור עמודה שנמחקה, מתוך שורת הלוג — כולל הערכים שהיו בה.

Deleting a column removes it from the board's settings and touches nothing
else: every item's value for it stays in custom_fields, keyed by the column
id, and is never cleaned up. The data therefore always survived a deletion.
What did not survive was the column — its type, options, width, and where it
sat — so there was nothing to restore the values into, and the log line could
only report the loss.

The definition is kept now, in a bin on the board, under the id of the log
row that recorded the deletion. That pairing is the whole design: the line
offers its own button, the entry is consumed when it is used, and a line
whose entry is gone stops offering.

Pinned here: the values come back, the column lands where it was, the offer
is single-use, only a board admin may take it, and an id that is live again
is refused rather than duplicated. The wording and the button are pinned by
tests/frontend/column_restore_line.mjs.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "column_restore_line.mjs"

COLS = [{"id": "col_r1", "title": "תקציב", "type": "number", "width": 120},
        {"id": "col_r2", "title": "הערות", "type": "text", "width": 200}]


def _board(client, admin_id):
    bid = client.post("/api/boards", json={"name": "לוח עמודות",
                                           "user_id": admin_id}).json()["id"]
    client.patch(f"/api/boards/{bid}", json={"columns": [dict(c) for c in COLS],
                                             "user_id": admin_id})
    return bid


def _delete_first_column(client, bid, admin_id):
    client.patch(f"/api/boards/{bid}", json={"columns": [dict(COLS[1])],
                                             "user_id": admin_id})
    rows = client.get(f"/api/boards/{bid}/activity?user_id={admin_id}").json()["activity"]
    return next(r for r in rows if r["field"] == "column" and r["action"] == "delete")


def test_the_values_come_back_with_the_column(client, admin_id):
    bid = _board(client, admin_id)
    try:
        tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                              "user_id": admin_id}).json()["id"]
        client.patch(f"/api/tasks/{tid}", json={"custom_fields": {"col_r1": 4200},
                                                "user_id": admin_id})
        row = _delete_first_column(client, bid, admin_id)
        assert row["can_restore_column"] is True

        r = client.post(f"/api/boards/{bid}/columns/restore",
                        json={"log_id": row["id"], "user_id": admin_id})
        assert r.status_code == 200, r.text

        board = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
        assert [c["title"] for c in board["columns"]] == ["תקציב", "הערות"], \
            "the column did not come back in the place it was taken from"
        item = next(t for t in board["tasks"] if t["id"] == tid)
        assert item["custom_fields"].get("col_r1") == 4200, \
            "the column came back empty — the values were not what survived"
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_offer_is_single_use(client, admin_id):
    """The bin entry is the authority, so the same line cannot restore twice —
    and after it is spent the line stops advertising a button that would fail."""
    bid = _board(client, admin_id)
    try:
        row = _delete_first_column(client, bid, admin_id)
        assert client.post(f"/api/boards/{bid}/columns/restore",
                           json={"log_id": row["id"], "user_id": admin_id}).status_code == 200

        again = client.post(f"/api/boards/{bid}/columns/restore",
                            json={"log_id": row["id"], "user_id": admin_id})
        assert again.status_code == 404, again.text

        rows = client.get(f"/api/boards/{bid}/activity?user_id={admin_id}").json()["activity"]
        spent = next(r for r in rows if r["id"] == row["id"])
        assert spent["can_restore_column"] is False
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_a_restore_is_written_to_the_log_too(client, admin_id):
    bid = _board(client, admin_id)
    try:
        row = _delete_first_column(client, bid, admin_id)
        client.post(f"/api/boards/{bid}/columns/restore",
                    json={"log_id": row["id"], "user_id": admin_id})
        rows = client.get(f"/api/boards/{bid}/activity?user_id={admin_id}").json()["activity"]
        back = [r for r in rows if r["field"] == "column" and r["action"] == "restore"]
        assert len(back) == 1, back
        assert back[0]["new"] == "תקציב"
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_only_a_board_admin_may_restore(client, admin_id, guinea_id):
    """Adding a column is an admin's decision on this board; so is undoing a
    removal. An editor fills the board in, they do not decide its shape."""
    bid = _board(client, admin_id)
    try:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
        row = _delete_first_column(client, bid, admin_id)
        r = client.post(f"/api/boards/{bid}/columns/restore",
                        json={"log_id": row["id"], "user_id": guinea_id})
        assert r.status_code == 403, r.text
        # and the offer is still intact for somebody who may take it
        assert client.post(f"/api/boards/{bid}/columns/restore",
                           json={"log_id": row["id"], "user_id": admin_id}).status_code == 200
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_an_id_that_is_live_again_is_refused(client, admin_id):
    """Two columns sharing an id would both answer from one stored value."""
    bid = _board(client, admin_id)
    try:
        row = _delete_first_column(client, bid, admin_id)
        # somebody re-creates a column on the same id before the restore
        client.patch(f"/api/boards/{bid}",
                     json={"columns": [dict(COLS[1]),
                                       {"id": "col_r1", "title": "אחר", "type": "text"}],
                           "user_id": admin_id})
        r = client.post(f"/api/boards/{bid}/columns/restore",
                        json={"log_id": row["id"], "user_id": admin_id})
        assert r.status_code == 409, r.text
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_line_and_its_button():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
