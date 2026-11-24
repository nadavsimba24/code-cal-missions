"""Undoing a change in a log is the board admin's, decided per board.

It used to be decided by the account's system role: anybody whose account said
admin or manager could press "בטל" on any line of any log, while the admin of
the board itself could not, unless their account happened to say manager too.
That is wrong in both directions. A system manager who was never invited to a
board could rewrite its items' history, and the person who actually runs the
board had no way to take back a change made on it.

Pinned here, on both halves — the server refusing, and the log offering the
button (can_undo) only to the person the server would let through:

- the board's admin may undo, even though their account is an ordinary member;
- an editor of the same board may not;
- a system manager who is not on the board may not;
- the system administrator still may, because they are admin of every board.
"""
import pytest

from conftest import join_primary_env


def AS(uid):
    return {"X-CityOS-User": str(uid)}


def _user(client, admin_id, name, email, role="member"):
    for u in client.get("/api/users", headers=AS(admin_id)).json():
        if u.get("email") == email:
            uid = u["id"]
            break
    else:
        r = client.post("/api/users", headers=AS(admin_id),
                        json={"name": name, "email": email, "role": role})
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
    join_primary_env(client, uid)
    return uid


@pytest.fixture
def board(client, admin_id):
    r = client.post("/api/boards", headers=AS(admin_id),
                    json={"name": "ביטול רק למנהל לוח", "workspace_id": 1})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        yield bid
    finally:
        client.delete(f"/api/boards/{bid}", headers=AS(admin_id))


@pytest.fixture
def people(client, admin_id, board):
    boss = _user(client, admin_id, "מנהלת לוח", "undo.board.admin@cityos.test")
    editor = _user(client, admin_id, "עורך לוח", "undo.board.editor@cityos.test")
    outsider = _user(client, admin_id, "מנהל מערכת חיצוני",
                     "undo.sys.manager@cityos.test", role="manager")
    for uid, role in ((boss, "admin"), (editor, "editor")):
        r = client.post(f"/api/boards/{board}/members", headers=AS(admin_id),
                        json={"user_id": uid, "role": role})
        assert r.status_code == 200, r.text
    return {"boss": boss, "editor": editor, "outsider": outsider}


def _a_change(client, admin_id, board):
    """An item renamed once, and the log line that rename wrote."""
    r = client.post("/api/tasks", headers=AS(admin_id),
                    json={"board_id": board, "title": "לפני"})
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    r = client.patch(f"/api/tasks/{tid}", headers=AS(admin_id), json={"title": "אחרי"})
    assert r.status_code == 200, r.text
    log = client.get(f"/api/tasks/{tid}/activity", headers=AS(admin_id)).json()["activity"]
    line = next(a for a in log if a["field"] == "title" and a["action"] == "update")
    return tid, line["id"]


def _can_undo(client, uid, board, tid, log_id):
    """What the item log and the board log each say to this viewer."""
    item = client.get(f"/api/tasks/{tid}/activity", headers=AS(uid)).json()["activity"]
    whole = client.get(f"/api/boards/{board}/activity", headers=AS(uid)).json()["activity"]
    return (next(a for a in item if a["id"] == log_id)["can_undo"],
            next(a for a in whole if a["id"] == log_id)["can_undo"])


def test_the_board_admin_undoes_a_change_with_an_ordinary_account(client, admin_id, board, people):
    tid, log_id = _a_change(client, admin_id, board)
    assert _can_undo(client, people["boss"], board, tid, log_id) == (True, True)
    r = client.post(f"/api/activity/{log_id}/undo", headers=AS(people["boss"]), json={})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/tasks/{tid}", headers=AS(admin_id)).json()["title"] == "לפני"


def test_an_editor_of_the_board_is_not_offered_undo_and_is_refused(client, admin_id, board, people):
    tid, log_id = _a_change(client, admin_id, board)
    assert _can_undo(client, people["editor"], board, tid, log_id) == (False, False)
    r = client.post(f"/api/activity/{log_id}/undo", headers=AS(people["editor"]), json={})
    assert r.status_code == 403, r.text
    assert client.get(f"/api/tasks/{tid}", headers=AS(admin_id)).json()["title"] == "אחרי"


def test_a_system_manager_off_the_board_cannot_undo_on_it(client, admin_id, board, people):
    tid, log_id = _a_change(client, admin_id, board)
    r = client.post(f"/api/activity/{log_id}/undo", headers=AS(people["outsider"]), json={})
    assert r.status_code == 403, r.text
    assert client.get(f"/api/tasks/{tid}", headers=AS(admin_id)).json()["title"] == "אחרי"


def test_the_system_administrator_still_undoes_anywhere(client, admin_id, board, people):
    tid, log_id = _a_change(client, admin_id, board)
    assert _can_undo(client, admin_id, board, tid, log_id) == (True, True)
    r = client.post(f"/api/activity/{log_id}/undo", headers=AS(admin_id), json={})
    assert r.status_code == 200, r.text
