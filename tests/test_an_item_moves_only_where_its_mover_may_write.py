"""An item changes board only through /move, and only into a board its mover
may edit.

The penetration test of 2026-11 sent PATCH /api/tasks/{id} with {"board_id": 2},
got a 200, and then a 403 reading the item back — and reported it as the item
having been moved into a board the caller could not write to. The PATCH never
applied board_id; what it did was answer as though nothing was wrong. Pinned
here: server-owned fields in a PATCH are refused by name (400) and change
nothing, and the real move refuses a target board the mover cannot edit (403)
and leaves the item where it was.
"""
import pytest

H = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    bid = client.post("/api/boards", json={"name": name}, headers=H(admin_id)).json()["id"]
    gid = client.get(f"/api/boards/{bid}", headers=H(admin_id)).json()["groups"][0]["id"]
    return bid, gid


@pytest.fixture
def two_boards(client, admin_id, guinea_id):
    """Source: guinea edits it. Target: guinea only reads it."""
    src, gid = _board(client, admin_id, "לוח מקור")
    dst, _ = _board(client, admin_id, "לוח יעד")
    client.post(f"/api/boards/{src}/members", json={"user_id": guinea_id, "role": "editor"},
                headers=H(admin_id))
    client.post(f"/api/boards/{dst}/members", json={"user_id": guinea_id, "role": "viewer"},
                headers=H(admin_id))
    t = client.post("/api/tasks", json={"board_id": src, "group_id": gid, "title": "פריט"},
                    headers=H(admin_id)).json()
    try:
        yield src, dst, t["id"]
    finally:
        for b in (src, dst):
            client.delete(f"/api/boards/{b}", headers=H(admin_id))


@pytest.mark.parametrize("field,value", [("board_id", 0), ("group_id", 0), ("parent_id", 0),
                                         ("is_archived", True), ("permissions", {"1": "none"})])
def test_a_patch_naming_a_server_owned_field_is_refused_and_changes_nothing(
        client, guinea_id, two_boards, field, value):
    src, dst, tid = two_boards
    value = dst if field == "board_id" else value
    r = client.patch(f"/api/tasks/{tid}", json={field: value, "title": "לא נשמר"},
                     headers=H(guinea_id))
    assert r.status_code == 400, r.text
    assert field in r.json()["detail"]
    t = client.get(f"/api/tasks/{tid}", headers=H(guinea_id)).json()
    assert t["board_id"] == src and t["title"] == "פריט"


def test_a_move_into_a_board_the_mover_only_reads_is_refused(client, guinea_id, two_boards):
    src, dst, tid = two_boards
    r = client.post(f"/api/tasks/{tid}/move", json={"board_id": dst}, headers=H(guinea_id))
    assert r.status_code == 403, r.text
    assert client.get(f"/api/tasks/{tid}", headers=H(guinea_id)).json()["board_id"] == src


def test_an_ordinary_edit_still_goes_through(client, guinea_id, two_boards):
    src, _dst, tid = two_boards
    r = client.patch(f"/api/tasks/{tid}", json={"title": "נשמר"}, headers=H(guinea_id))
    assert r.status_code == 200, r.text
    assert client.get(f"/api/tasks/{tid}", headers=H(guinea_id)).json()["title"] == "נשמר"
