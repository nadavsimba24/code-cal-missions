"""סינון לפי אחראי חייב להחזיר את כל הפריטים המתאימים, לא את העמוד הראשון שלהם.

"עשיתי סינון לפי אחראי — ואני אחראית על הפריט — והוא לא מופיע."

/api/boards/{id}/items/query answers in one of two shapes, and the caller
says which. A board the browser filters itself needs the IDS — it already
holds every row, and all it is missing is which of them survive. A board too
large to hold needs a PAGE of rows, because the page is what will be drawn.

The browser asked for neither and got the page by default: the first
QUERY_PAGE ids. applyFilters then reads item_ids as the whole answer and
keeps only the rows named in it, so on a board where more than fifty items
carried the filtered person, every match past the fiftieth was removed from
the board — silently, with the badge still counting and the filter still lit.
The rows that went were whichever sat lowest in the board's own order, which
is why it read as "it skips items" rather than as "filtering is broken".

Pinned here on the server side: ids_only answers about every match, and the
paged shape is the page it says it is. The browser's half — that it asks with
ids_only, and that it refuses a list the server marked `truncated` — is
pinned by tests/frontend/filter_asks_for_ids.mjs.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "filter_asks_for_ids.mjs"


MINE = {"filter": {"type": "group", "operator": "and",
                   "rules": [{"type": "rule", "field": "assignees",
                              "operator": "has", "value": "me"}]},
        "today": "2026-11-01", "tz_offset": 120}


@pytest.fixture
def board_of_mine(client, admin_id):
    """A board with more than one page of items, every one of them mine."""
    bid = client.post("/api/boards",
                      json={"actor_id": admin_id, "name": "לוח לבדיקת סינון"}).json()["id"]
    gid = client.post("/api/groups",
                      json={"actor_id": admin_id, "board_id": bid, "name": "קבוצה"}).json()["id"]
    made = []
    for i in range(60):
        t = client.post("/api/tasks", json={"actor_id": admin_id, "board_id": bid,
                                            "group_id": gid, "title": f"פריט {i:03d}"}).json()
        client.post(f"/api/tasks/{t['id']}/assignees",
                    json={"actor_id": admin_id, "user_id": admin_id})
        made.append(t["id"])
    try:
        yield bid, made
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_ids_only_names_every_item_that_matched(client, admin_id, board_of_mine):
    bid, made = board_of_mine
    r = client.post(f"/api/boards/{bid}/items/query",
                    json={**MINE, "ids_only": True, "user_id": admin_id})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["matched"] == len(made)
    # the whole point: the list is the answer, not a window onto it
    assert sorted(j["item_ids"]) == sorted(made)
    assert j.get("truncated") is False


def test_without_ids_only_the_answer_is_a_page_and_says_so(client, admin_id, board_of_mine):
    """The shape the browser must not ask for on a board it filters itself.

    Not a defect — it is the large-board answer doing its job. It is pinned
    so that the two shapes stay different things: the day item_ids here
    quietly becomes the full list, the test above stops proving anything."""
    bid, made = board_of_mine
    j = client.post(f"/api/boards/{bid}/items/query",
                    json={**MINE, "user_id": admin_id}).json()
    assert j["matched"] == len(made)
    assert len(j["item_ids"]) < len(made)      # a page, cut out of the matches
    assert j["has_more"] is True               # and it says as much


def test_a_sub_item_brings_its_parent_along(client, admin_id):
    """A board whose lines are sub-items answers about those lines.

    The rows somebody writes under "לוחות" are sub-items, and the parent
    carries no assignee at all. Filtering by a person has to reach them, and
    the parent comes back as context — present to say WHERE the match is,
    marked so it does not read as a row that answered."""
    bid = client.post("/api/boards",
                      json={"actor_id": admin_id, "name": "לוח עם תת-פריטים"}).json()["id"]
    gid = client.post("/api/groups",
                      json={"actor_id": admin_id, "board_id": bid, "name": "קבוצה"}).json()["id"]
    try:
        parent = client.post("/api/tasks", json={"actor_id": admin_id, "board_id": bid,
                                                 "group_id": gid, "title": "לוחות"}).json()
        sub = client.post("/api/tasks",
                          json={"actor_id": admin_id, "board_id": bid, "group_id": gid,
                                "parent_id": parent["id"],
                                "title": "ביצוע מיון בעמודה מקפיץ חזרה לצד הימני"}).json()
        client.post(f"/api/tasks/{sub['id']}/assignees",
                    json={"actor_id": admin_id, "user_id": admin_id})
        j = client.post(f"/api/boards/{bid}/items/query",
                        json={**MINE, "ids_only": True, "user_id": admin_id}).json()
        assert j["matched_subs"] == 1
        assert j["matched_own"] == 0
        assert parent["id"] in j["item_ids"]       # …or the sub-item has nowhere to hang
        assert j["matched_context"] == 1
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_browser_asks_in_the_shape_whose_answer_is_complete():
    """The other half of the bug, and the half no API test can see: which of
    the two shapes the browser asks for, and what it does with an answer the
    server itself marked as cut. See the harness for both."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
