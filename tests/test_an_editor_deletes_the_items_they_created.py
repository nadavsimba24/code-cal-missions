"""עורך בלוח יכול למחוק את הרשומות שהוא עצמו יצר — ורק אותן.

Until now only a board admin held "delete" on an item, so a row an editor added
by mistake waited for an admin to remove it, though nobody else had touched it.

What is pinned: an editor deletes an item they created (to the recycle bin, as
any delete); an editor still cannot delete an item somebody else created; a
viewer gets nothing from having created an item; an item override set by the
admin still wins over the new grant; and a board frozen to view-only freezes
the grant with it. The item's my_perm — which the screen draws the delete
button from — says the same as the server does.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import Board, Task


def _board(client, admin_id):
    return client.post("/api/boards", json={"name": "לוח מחיקה", "user_id": admin_id}).json()["id"]


def _invite(client, bid, admin_id, uid, role):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    assert r.status_code == 200, r.text


def _item(client, bid, actor, title="רשומה"):
    r = client.post("/api/tasks", json={"board_id": bid, "title": title, "user_id": actor})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _delete(client, tid, actor):
    return client.delete(f"/api/tasks/{tid}", headers={"X-CityOS-User": str(actor)})


def _in_bin(tid):
    with Session(cityos_main.engine) as db:
        # the app's queries hide the bin; this one is the way past that
        return cityos_main._deleted_tasks_q(db).filter(Task.id == tid).first().deleted_at is not None


def _my_perm(client, tid, actor):
    return client.get(f"/api/tasks/{tid}", headers={"X-CityOS-User": str(actor)}).json()["my_perm"]


def test_an_editor_deletes_an_item_they_created(client, admin_id, member_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, member_id, "editor")
    tid = _item(client, bid, member_id, "נוספה בטעות")
    assert _my_perm(client, tid, member_id) == "delete"
    r = _delete(client, tid, member_id)
    assert r.status_code == 200, r.text
    assert _in_bin(tid), "a delete goes to the recycle bin, where an admin can restore it"


def test_an_editor_cannot_delete_somebody_elses_item(client, admin_id, member_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, member_id, "editor")
    tid = _item(client, bid, admin_id, "של המנהל")
    assert _my_perm(client, tid, member_id) == "edit"
    assert _delete(client, tid, member_id).status_code == 403
    assert not _in_bin(tid)


def test_a_viewer_gains_nothing_from_having_created_an_item(client, admin_id, member_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, member_id, "editor")
    tid = _item(client, bid, member_id)
    _invite(client, bid, admin_id, member_id, "viewer")      # demoted afterwards
    assert _delete(client, tid, member_id).status_code == 403
    assert not _in_bin(tid)


def test_an_admins_item_override_still_wins(client, admin_id, member_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, member_id, "editor")
    tid = _item(client, bid, member_id)
    r = client.post(f"/api/tasks/{tid}/permissions",
                    json={"actor_id": admin_id, "user_id": member_id, "perm": "edit"})
    assert r.status_code == 200, r.text
    assert _my_perm(client, tid, member_id) == "edit"
    assert _delete(client, tid, member_id).status_code == 403


def test_a_view_only_board_freezes_the_grant(client, admin_id, member_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, member_id, "editor")
    tid = _item(client, bid, member_id)
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        b.settings = {**(b.settings or {}), "view_only": True}
        db.commit()
    assert _delete(client, tid, member_id).status_code == 403
    assert not _in_bin(tid)
    # …and the admin is not frozen by it
    assert _delete(client, tid, admin_id).status_code == 200
