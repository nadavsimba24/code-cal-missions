"""An e-mail column, as a type of its own rather than text holding an address.

The migration from monday brought boards whose contact address sat in a column
monday knows is an e-mail column. Flattening that into text loses the two
things the type is for — the address reads left-to-right on a right-to-left
board, and it is a link you can write to — so the type now exists here.

The grid behaviour lives in tests/frontend/email_column.mjs; what is asserted
here is that the server will actually keep such a column, and that a value
survives the round trip.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "email_column.mjs"


def _board(client, admin_id, name="דוא\"ל"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid, uid):
    return [c for c in client.get(f"/api/boards/{bid}?user_id={uid}").json()["columns"]
            if c["id"].startswith("col_")]


def test_a_board_admin_can_add_an_e_mail_column(client, admin_id):
    bid = _board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}", json={
        "columns": [{"id": "col_mail", "type": "email", "title": "דוא\"ל איש קשר"}],
        "user_id": admin_id})
    assert r.status_code == 200, r.text
    cols = _cols(client, bid, admin_id)
    assert [(c["type"], c["title"]) for c in cols] == [("email", "דוא\"ל איש קשר")]


def test_an_address_survives_the_round_trip(client, admin_id):
    bid = _board(client, admin_id)
    client.patch(f"/api/boards/{bid}", json={
        "columns": [{"id": "col_mail", "type": "email", "title": "דוא\"ל"}],
        "user_id": admin_id})
    t = client.post("/api/tasks", json={"board_id": bid, "title": "אבו גוש",
                                        "user_id": admin_id}).json()
    r = client.patch(f"/api/tasks/{t['id']}", json={
        "custom_fields": {"col_mail": "bhaa@abugosh.muni.il"}, "user_id": admin_id})
    assert r.status_code == 200, r.text
    board = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    got = next(x for x in board["tasks"] if x["id"] == t["id"])
    assert got["custom_fields"]["col_mail"] == "bhaa@abugosh.muni.il"


def test_a_column_type_the_system_does_not_have_is_still_refused(client, admin_id):
    """The allow-list grew by one entry; it did not stop being an allow-list."""
    bid = _board(client, admin_id)
    client.patch(f"/api/boards/{bid}", json={
        "columns": [{"id": "col_x", "type": "email", "title": "דוא\"ל"},
                    {"id": "col_y", "type": "vote", "title": "הצבעה"}],
        "user_id": admin_id})
    assert [c["type"] for c in _cols(client, bid, admin_id)] == ["email"]


def test_the_grid_treats_it_as_an_address_and_not_as_text():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
