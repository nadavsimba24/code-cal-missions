"""Every board has its own recycle bin for the items deleted from it."""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Task


def _mk_board(client, admin_id, name="לוח סל"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _mk_item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _titles(client, bid):
    return [t["title"] for t in client.get(f"/api/boards/{bid}").json()["tasks"]]


def test_deleting_hides_it_from_the_board_but_keeps_it(client, admin_id):
    bid = _mk_board(client, admin_id)
    tid = _mk_item(client, bid, admin_id, "פריט שנמחק")
    assert "פריט שנמחק" in _titles(client, bid)

    client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
    assert "פריט שנמחק" not in _titles(client, bid), "a deleted item is still on the board"
    with Session(cityos_main.engine) as db:
        row = db.query(Task).execution_options(include_deleted=True).filter(Task.id == tid).first()
    assert row is not None and row.deleted_at is not None, "the row was destroyed, not binned"


def test_the_bin_is_per_board(client, admin_id):
    """A board's bin shows its own items and nobody else's."""
    a, b = _mk_board(client, admin_id, "לוח א"), _mk_board(client, admin_id, "לוח ב")
    ta, tb = _mk_item(client, a, admin_id, "של א"), _mk_item(client, b, admin_id, "של ב")
    client.delete(f"/api/tasks/{ta}?user_id={admin_id}")
    client.delete(f"/api/tasks/{tb}?user_id={admin_id}")
    assert [i["title"] for i in client.get(f"/api/boards/{a}/trash").json()["items"]] == ["של א"]
    assert [i["title"] for i in client.get(f"/api/boards/{b}/trash").json()["items"]] == ["של ב"]


def test_restore_brings_it_back(client, admin_id):
    bid = _mk_board(client, admin_id)
    tid = _mk_item(client, bid, admin_id, "חוזר")
    client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
    assert client.post(f"/api/tasks/{tid}/restore", json={"actor_id": admin_id}).status_code == 200
    assert "חוזר" in _titles(client, bid)
    assert client.get(f"/api/boards/{bid}/trash").json()["items"] == []


def test_sub_items_follow_their_parent_both_ways(client, admin_id):
    """Deleting a parent bins its sub-items; restoring brings them back with it."""
    bid = _mk_board(client, admin_id)
    tid = _mk_item(client, bid, admin_id, "אב")
    sub = client.post("/api/tasks", json={"parent_id": tid, "title": "תת", "user_id": admin_id}).json()["id"]
    client.delete(f"/api/tasks/{tid}?user_id={admin_id}")

    listed = client.get(f"/api/boards/{bid}/trash").json()["items"]
    assert len(listed) == 1, "a sub-item was listed separately from its parent"
    assert listed[0]["sub_count"] == 1
    with Session(cityos_main.engine) as db:
        s = db.query(Task).execution_options(include_deleted=True).filter(Task.id == sub).first()
    assert s.deleted_at is not None

    client.post(f"/api/tasks/{tid}/restore", json={"actor_id": admin_id})
    board = client.get(f"/api/boards/{bid}").json()
    parent = next(t for t in board["tasks"] if t["id"] == tid)
    assert [s["title"] for s in (parent.get("subtasks") or [])] == ["תת"]


def test_viewing_a_binned_item_does_not_restore_it(client, admin_id):
    bid = _mk_board(client, admin_id)
    tid = _mk_item(client, bid, admin_id, "לצפייה")
    client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
    r = client.get(f"/api/boards/{bid}/trash/{tid}")
    assert r.status_code == 200 and r.json()["title"] == "לצפייה"
    assert "לצפייה" not in _titles(client, bid), "viewing restored it"


def test_permanent_delete_is_permanent(client, admin_id):
    bid = _mk_board(client, admin_id)
    tid = _mk_item(client, bid, admin_id, "לתמיד")
    client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
    assert client.delete(f"/api/boards/{bid}/trash/{tid}?actor_id={admin_id}").status_code == 200
    assert client.get(f"/api/boards/{bid}/trash").json()["items"] == []
    with Session(cityos_main.engine) as db:
        assert db.query(Task).execution_options(include_deleted=True).filter(Task.id == tid).first() is None
    assert client.post(f"/api/tasks/{tid}/restore", json={"actor_id": admin_id}).status_code == 404


def test_only_a_board_admin_may_delete_permanently(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    tid = _mk_item(client, bid, admin_id, "לא נמחק")
    client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
    r = client.delete(f"/api/boards/{bid}/trash/{tid}?actor_id={guinea_id}")
    assert r.status_code == 403
    assert len(client.get(f"/api/boards/{bid}/trash").json()["items"]) == 1


def test_a_non_member_cannot_see_the_bin(client, admin_id):
    bid = _mk_board(client, admin_id)
    email = "bin.outsider@cityos.test"
    for u in client.get("/api/users").json():
        if u.get("email") == email:
            uid = u["id"]; break
    else:
        uid = client.post("/api/users", json={"actor_id": admin_id, "name": "זר",
                                              "email": email, "role": "member"}).json()["id"]
    client.delete(f"/api/boards/1/members/{uid}?actor_id={admin_id}")
    assert client.get(f"/api/boards/{bid}/trash",
                      headers={"X-CityOS-User": str(uid)}).status_code == 403


def test_a_binned_item_stays_out_of_counts_and_search(client, admin_id):
    """The hook has to cover every read, not just the board payload."""
    bid = _mk_board(client, admin_id)
    tid = _mk_item(client, bid, admin_id, "ייחודי-לחיפוש")
    before = next(b for b in client.get("/api/boards").json() if b["id"] == bid)["task_count"]
    client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
    after = next(b for b in client.get("/api/boards").json() if b["id"] == bid)["task_count"]
    assert after == before - 1, "a deleted item is still counted on the board list"
