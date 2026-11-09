"""פריט חדש נכנס בתחתית הקבוצה, גם אחרי שמחקו ממנה.

"כאשר מוסיפים פריט חדש מהשורה האחרונה בקבוצה הוא מוסיף אותו במיקום רנדומלי
במקום בתחתית הקבוצה" — and "sometimes", which is the part that says what it
was. Two faults, one on each side of the same number:

  · A new item was placed at max(position) + 1 over the group — and
    _hide_deleted_tasks takes the recycle bin out of that question like it
    takes it out of every other one. A deleted item keeps its number, so the
    group whose bottom row had been deleted handed that row's number straight
    back to the next "+ הוסף פריט". Restoring the old item then put two items
    in one slot. Groups nothing had been deleted from were fine, which is
    exactly how a bug comes to happen "sometimes".
  · And the board read its rows back with ORDER BY position and nothing else,
    so a tie was the database's to break — differently on consecutive reads if
    it liked. Rows swapped places on a refresh that changed nothing.

Both halves are needed: the first stops new collisions, the second makes the
ones already sitting in every existing board resolve the same way twice.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import Task

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name="לוח תחתית"):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _group(client, bid, admin_id, name="קבוצה"):
    return client.post("/api/groups",
                       json={"board_id": bid, "name": name,
                             "actor_id": admin_id}).json()["id"]


def _add(client, bid, admin_id, title, gid=None, parent=None):
    body = {"board_id": bid, "title": title, "user_id": admin_id}
    if gid is not None:
        body["group_id"] = gid
    if parent is not None:
        body["parent_id"] = parent
    r = client.post("/api/tasks", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _shown(client, bid, admin_id, gid):
    """The titles of a group's rows, in the order the board hands them over."""
    b = client.get(f"/api/boards/{bid}", headers=AS(admin_id)).json()
    return [t["title"] for t in b["tasks"] if t["group_id"] == gid]


# ── the bottom row ────────────────────────────────────────────────────────

def test_a_new_item_is_the_last_row_of_its_group(client, admin_id):
    bid = _board(client, admin_id)
    gid = _group(client, bid, admin_id)
    for n in ("א", "ב", "ג"):
        _add(client, bid, admin_id, n, gid)
    _add(client, bid, admin_id, "חדש", gid)
    assert _shown(client, bid, admin_id, gid) == ["א", "ב", "ג", "חדש"]


def test_a_number_held_by_an_item_in_the_bin_is_not_handed_out_again(
        client, admin_id):
    """The reported sequence: delete the bottom row, add one from the last
    line, and the new item is holding the deleted one's slot."""
    bid = _board(client, admin_id, "לוח סל")
    gid = _group(client, bid, admin_id)
    made = [_add(client, bid, admin_id, n, gid) for n in ("א", "ב", "ג")]
    assert client.delete(f"/api/tasks/{made[-1]['id']}",
                         headers=AS(admin_id)).status_code == 200
    fresh = _add(client, bid, admin_id, "חדש", gid)
    with Session(cityos_main.engine) as db:
        binned = (db.query(Task).execution_options(include_deleted=True)
                    .filter(Task.id == made[-1]["id"]).first())
        assert fresh["position"] != binned.position, (
            "the new item took the slot of the item in the bin")
        assert fresh["position"] > binned.position, "and it belongs below it"


def test_restoring_the_deleted_item_leaves_the_new_one_at_the_bottom(
        client, admin_id):
    """The moment the collision became visible: a restore put both items in
    one slot and the board picked between them."""
    bid = _board(client, admin_id, "לוח שחזור")
    gid = _group(client, bid, admin_id)
    made = [_add(client, bid, admin_id, n, gid) for n in ("א", "ב", "ג")]
    client.delete(f"/api/tasks/{made[-1]['id']}", headers=AS(admin_id))
    _add(client, bid, admin_id, "חדש", gid)
    assert client.post(f"/api/tasks/{made[-1]['id']}/restore", json={},
                       headers=AS(admin_id)).status_code == 200
    assert _shown(client, bid, admin_id, gid) == ["א", "ב", "ג", "חדש"]


def test_a_group_emptied_into_the_bin_still_counts_what_is_in_it(
        client, admin_id):
    """Every row deleted: max over the living is nothing at all, and the next
    item used to start again at zero — on top of all of them."""
    bid = _board(client, admin_id, "לוח ריק")
    gid = _group(client, bid, admin_id)
    made = [_add(client, bid, admin_id, n, gid) for n in ("א", "ב")]
    for t in made:
        client.delete(f"/api/tasks/{t['id']}", headers=AS(admin_id))
    _add(client, bid, admin_id, "חדש", gid)
    for t in made:
        client.post(f"/api/tasks/{t['id']}/restore", json={}, headers=AS(admin_id))
    assert _shown(client, bid, admin_id, gid) == ["א", "ב", "חדש"]


def test_a_sub_item_lands_under_the_last_sub_item(client, admin_id):
    """A parent's sub-list is the same question asked of parent_id."""
    bid = _board(client, admin_id, "לוח תתי")
    gid = _group(client, bid, admin_id)
    p = _add(client, bid, admin_id, "אב", gid)
    subs = [_add(client, bid, admin_id, n, gid, parent=p["id"]) for n in ("א", "ב")]
    client.delete(f"/api/tasks/{subs[-1]['id']}", headers=AS(admin_id))
    fresh = _add(client, bid, admin_id, "חדש", gid, parent=p["id"])
    client.post(f"/api/tasks/{subs[-1]['id']}/restore", json={}, headers=AS(admin_id))
    b = client.get(f"/api/boards/{bid}", headers=AS(admin_id)).json()
    kids = [t for t in b["tasks"] if t["id"] == p["id"]][0]["subtasks"]
    assert [k["title"] for k in kids] == ["א", "ב", "חדש"], kids
    assert fresh["position"] > subs[-1]["position"]


# ── and a tie that already exists resolves the same way twice ─────────────

def test_two_items_sharing_a_slot_come_back_in_the_same_order(client, admin_id):
    """Every board built before the fix above has groups where two items claim
    one position. ORDER BY position alone left that to the database, and the
    rows swapped places on a refresh that changed nothing."""
    bid = _board(client, admin_id, "לוח תיקו")
    gid = _group(client, bid, admin_id)
    made = [_add(client, bid, admin_id, n, gid) for n in ("א", "ב", "ג")]
    # the collision as it exists on a real board, written here rather than
    # re-created through the path that no longer produces it
    with Session(cityos_main.engine) as db:
        for t in made:
            db.query(Task).filter(Task.id == t["id"]).update({"position": 0})
        db.commit()
    first = _shown(client, bid, admin_id, gid)
    assert first == ["א", "ב", "ג"], first      # oldest first, by id
    for _ in range(3):
        assert _shown(client, bid, admin_id, gid) == first
    # …and an item added to that group is still the bottom row of it
    _add(client, bid, admin_id, "חדש", gid)
    assert _shown(client, bid, admin_id, gid) == ["א", "ב", "ג", "חדש"]
