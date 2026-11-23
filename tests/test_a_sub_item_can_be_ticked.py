"""תת-פריט מקבל צ'ק-בוקס, כמו פריט.

An item row has carried a selection box for a long time, feeding the bulk bar
(duplicate, move, delete); a sub-item row had none, and the bar's helpers
dropped sub-items on purpose. What is pinned now:

  · a sub-item the person may edit has the same box, in the same selection;
  · the sub-item table's header has a box for all of one parent's sub-items,
    with the group box's three states;
  · delete and duplicate act on ticked sub-items — a copy lands under the same
    parent, and a sub-item whose parent is also ticked is not deleted twice;
  · move does not, because a sub-item travels with its parent, and says so;
  · folding a panel takes its sub-items out of the selection, so the bar never
    acts on rows nobody can see.

The server half — that a copy posted with only a parent_id lands under that
parent — is checked here against the real endpoint.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_a_sub_item_copy_posted_with_only_its_parent_lands_under_that_parent(client, admin_id):
    r = client.post("/api/boards", json={"name": "ticked subs", "department_id": 1, "user_id": admin_id})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        parent = client.post("/api/tasks", json={"board_id": bid, "title": "P", "user_id": admin_id}).json()
        # the body bulkDuplicate sends for a sub-item: no board, no group
        copy = client.post("/api/tasks", json={"parent_id": parent["id"], "title": "s (עותק)",
                                               "user_id": admin_id})
        assert copy.status_code == 200, copy.text
        c = copy.json()
        assert c["parent_id"] == parent["id"]
        assert c["board_id"] == bid
        assert c["group_id"] == parent["group_id"]
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_sub_item_box_and_the_bulk_bar():
    """Driven harness: tests/frontend/a_sub_item_can_be_ticked.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "a_sub_item_can_be_ticked.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
