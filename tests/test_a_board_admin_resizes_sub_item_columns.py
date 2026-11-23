"""מנהל לוח מרחיב ומצמצם עמודה בטבלת תתי-הפריטים.

The sub-item table is its own narrower table, set in under the parent row.
It used to borrow the item table's widths and pin the sub-item name at 260px,
so nobody could make a sub-item column wider or narrower on its own.

The rule pinned here is the same one col_widths has had all along: the widths
are a property of the board, stored in its settings as `sub_col_widths`, set
only by a board admin, clamped to 60..600, and they never touch the item
table's `col_widths`.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def board(client, admin_id, member_id):
    r = client.post("/api/boards", json={"name": "sub widths", "department_id": 1, "user_id": admin_id})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        yield bid
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_a_board_admin_saves_sub_item_widths_and_they_come_back_with_the_board(client, admin_id, board):
    r = client.patch(f"/api/boards/{board}", json={
        "user_id": admin_id,
        "sub_col_widths": {"item": 400, "status": 5000, "due": 10, "bad": "x"},
    })
    assert r.status_code == 200, r.text
    b = client.get(f"/api/boards/{board}?user_id={admin_id}").json()
    sw = b.get("sub_col_widths")
    assert sw == {"item": 400, "status": 600, "due": 60}, sw


def test_sub_item_widths_leave_the_item_table_alone(client, admin_id, board):
    client.patch(f"/api/boards/{board}", json={"user_id": admin_id, "col_widths": {"status": 200}})
    client.patch(f"/api/boards/{board}", json={"user_id": admin_id, "sub_col_widths": {"status": 90}})
    b = client.get(f"/api/boards/{board}?user_id={admin_id}").json()
    assert b["col_widths"] == {"status": 200}
    assert b["sub_col_widths"] == {"status": 90}


def test_a_board_that_never_resized_a_sub_item_column_sends_an_empty_map(client, admin_id, board):
    b = client.get(f"/api/boards/{board}?user_id={admin_id}").json()
    assert b.get("sub_col_widths") == {}


def test_a_member_who_is_not_a_board_admin_cannot_resize_sub_item_columns(client, member_id):
    r = client.patch("/api/boards/1", json={"user_id": member_id, "sub_col_widths": {"item": 300}})
    assert r.status_code == 403


def test_the_sub_item_table_draws_and_saves_its_own_widths():
    """Driven harness: tests/frontend/a_sub_item_column_has_its_own_width.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "a_sub_item_column_has_its_own_width.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
