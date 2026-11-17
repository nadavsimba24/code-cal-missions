"""הוספת פריט — הפריט נוחת במקום שהכפתור הבטיח.

There are two ways to add an item and they mean two different places. The
"+ הוסף פריט" line is the last row of a group, and the row it makes belongs
after the last one — it says nothing and the server appends. The "פריט חדש"
button is at the top of the board, above every group, and the row it makes
belongs at the top: a board is read downwards, and an item added from up there
that arrives eighty rows below the fold is an item nobody sees. It says so by
sending position 0.

What is pinned here is that asking for a place is enough to get it — and that
the rest of the group makes room rather than tying with it. A position written
as a bare number would leave two items claiming 0, and every query that returns
items reads back ordered by position: the tie then goes to whichever row the
database felt like, which is the drag-springs-back bug arriving by a different
road.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "new_item_lands_where_it_was_asked_for.mjs"


def _board(client, name):
    b = client.post("/api/boards", json={"name": name, "workspace_id": 1}).json()
    g = client.post("/api/groups", json={"board_id": b["id"], "name": "G"}).json()
    return b["id"], g["id"]


def _order(client, bid, gid):
    board = client.get(f"/api/boards/{bid}").json()
    return [t["title"] for t in board["tasks"] if t.get("group_id") == gid]


def test_an_item_that_names_no_place_goes_to_the_bottom(client):
    """The "+ הוסף פריט" line, which is where the bottom of the group is."""
    bid, gid = _board(client, "bottom")
    for n in ("a", "b", "c"):
        client.post("/api/tasks", json={"board_id": bid, "group_id": gid, "title": n})
    r = client.post("/api/tasks", json={"board_id": bid, "group_id": gid, "title": "חדש"})
    assert r.status_code == 200
    assert _order(client, bid, gid) == ["a", "b", "c", "חדש"]


def test_an_item_that_asks_for_the_top_gets_it(client):
    """...and the group moves down to make room, rather than tying with it."""
    bid, gid = _board(client, "top")
    for n in ("a", "b", "c"):
        client.post("/api/tasks", json={"board_id": bid, "group_id": gid, "title": n})
    r = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "חדש", "position": 0})
    assert r.status_code == 200
    assert r.json()["position"] == 0
    assert _order(client, bid, gid) == ["חדש", "a", "b", "c"]
    board = client.get(f"/api/boards/{bid}").json()
    pos = [t["position"] for t in board["tasks"] if t.get("group_id") == gid]
    assert pos == [0, 1, 2, 3], f"the group is not a dense sequence any more: {pos}"


def test_the_top_stays_the_top_however_the_numbers_got_there(client):
    """Positions are not always 0..n-1. A restore puts an item back on the
    number it had, an import arrives with gaps, and two items can hold the same
    number after one. Asking for the top has to mean the top in all of those —
    which is why it renumbers the group instead of writing a smaller number."""
    bid, gid = _board(client, "messy")
    ids = [client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                           "title": n}).json()["id"]
           for n in ("a", "b", "c")]
    # drag the last one to the front, the way a person would
    client.post(f"/api/tasks/{ids[2]}/move", json={"group_id": gid, "after_id": None})
    assert _order(client, bid, gid) == ["c", "a", "b"]
    client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                    "title": "חדש", "position": 0})
    assert _order(client, bid, gid) == ["חדש", "c", "a", "b"]


def test_a_position_that_is_not_a_number_is_a_bad_request(client):
    """400 and not 500: a bad argument is the caller's, and it is named."""
    bid, gid = _board(client, "bad")
    r = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "x", "position": "למעלה"})
    assert r.status_code == 400


def test_a_sub_item_is_not_placed_by_a_group_position(client):
    """A sub-item's position is an index in its parent's list, and placing one
    renumbers a GROUP — handed a sub-item it would renumber the items around
    the parent instead, which is a different list entirely. The only way to add
    a sub-item is the line at the foot of the sub-list, which means the bottom,
    so the field is ignored there rather than obeyed into the wrong list."""
    bid, gid = _board(client, "subs")
    parent = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                             "title": "אב"}).json()
    after = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                            "title": "אחרי"}).json()
    for n in ("s1", "s2"):
        client.post("/api/tasks", json={"parent_id": parent["id"], "title": n})
    client.post("/api/tasks", json={"parent_id": parent["id"], "title": "s3",
                                    "position": 0})
    board = client.get(f"/api/boards/{bid}").json()
    top = [t["title"] for t in board["tasks"] if t.get("group_id") == gid]
    assert top == ["אב", "אחרי"], "a sub-item reordered the group it hangs in"
    row = next(t for t in board["tasks"] if t["id"] == parent["id"])
    assert [s["title"] for s in row.get("subtasks", [])] == ["s1", "s2", "s3"]
    assert after["position"] == 1


def test_the_board_draws_a_group_in_its_own_order():
    """The other half of the same rule, on the browser's side: the rows are
    drawn in the board's order and not in whatever order the tasks array
    happens to be in. The two are the same thing until something changes one
    without rebuilding the other — a bulk "העברה לקבוצה" writes each item's new
    position from the server's answer and leaves the array alone — and then the
    next full re-render, which is what adding an item is, draws the group in an
    order nobody recognises with the new row somewhere inside it.

    Runs the real openNewItem, applyFilters and byPosition out of index.html
    under node; the harness names the failing case.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
