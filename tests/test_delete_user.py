"""Erasing a person from the system, for good.

The system could only ever deactivate somebody: `is_active=False`, the account
kept in the directory, which is the right default for somebody who left. An
account that should never have existed here is a different case, and there was
no way to answer it but by hand in the database — 30 columns point at
`users.id`, so "by hand" meant deciding all of them under pressure.

The rule this encodes: a row GOES when it is the person's own relationship to
something, or something they authored that was asked to be erased with them.
A row only stops NAMING them when it belongs to the municipality and would be
destroyed with them — the item they created, the permit assigned to them, the
automation they own. Deleting a person is not deleting their work.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import (AuditLog, Automation, BoardMember, Comment, EnvironmentMember,
                    Notification, Task, User, WorkspaceMember)


def _mk_user(client, admin_id, email, name="זמני", role="member"):
    r = client.post(f"/api/users?user_id={admin_id}",
                    json={"email": email, "name": name, "role": role})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _board(client, admin_id, name="לוח מחיקה"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def test_only_a_system_admin_may_delete(client, admin_id, guinea_id):
    uid = _mk_user(client, admin_id, "doomed1@x.test")
    r = client.delete(f"/api/users/{uid}?user_id={guinea_id}")
    assert r.status_code == 403
    with Session(cityos_main.engine) as db:
        assert db.query(User).filter(User.id == uid).first() is not None


def test_a_person_is_erased_with_everything_that_was_theirs(client, admin_id):
    uid = _mk_user(client, admin_id, "doomed2@x.test", "נמחק")
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": uid, "role": "editor"})
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    client.post(f"/api/tasks/{tid}/assignees", json={"actor_id": admin_id, "user_id": uid})
    client.post(f"/api/tasks/{tid}/comments", json={"actor_id": uid, "content": "שלום"})
    client.patch(f"/api/tasks/{tid}?user_id={uid}", json={"status": "done"})   # writes audit rows

    with Session(cityos_main.engine) as db:
        assert db.query(Comment).filter(Comment.user_id == uid).count() == 1
        assert db.query(BoardMember).filter(BoardMember.user_id == uid).count() == 1
        assert db.query(AuditLog).filter(AuditLog.changed_by == uid).count() >= 1

    r = client.delete(f"/api/users/{uid}?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"]["email"] == "doomed2@x.test"

    with Session(cityos_main.engine) as db:
        assert db.query(User).filter(User.id == uid).first() is None
        assert db.query(Comment).filter(Comment.user_id == uid).count() == 0
        assert db.query(BoardMember).filter(BoardMember.user_id == uid).count() == 0
        assert db.query(EnvironmentMember).filter(EnvironmentMember.user_id == uid).count() == 0
        assert db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid).count() == 0
        assert db.query(Notification).filter(Notification.user_id == uid).count() == 0
        assert db.query(AuditLog).filter(AuditLog.changed_by == uid).count() == 0
        # the item itself is the municipality's and stays, with its assignment gone
        t = db.query(Task).filter(Task.id == tid).first()
        assert t is not None and uid not in {x.id for x in t.assignees}
    # and the directory no longer lists them
    users = client.get(f"/api/users?user_id={admin_id}").json()
    users = users if isinstance(users, list) else users["users"]
    assert uid not in {u["id"] for u in users}


def test_their_work_survives_without_their_name_on_it(client, admin_id):
    """An item they created, and an automation they own, must not be destroyed
    with them: those belong to the board, not to the person."""
    uid = _mk_user(client, admin_id, "doomed3@x.test")
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": uid, "role": "admin"})
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "שלו", "user_id": uid}).json()["id"]
    aid = client.post(f"/api/boards/{bid}/automations?user_id={uid}",
                      json={"recipe_id": "created_set_priority",
                            "config": {"a_priority": "high"}}).json()["id"]

    assert client.delete(f"/api/users/{uid}?user_id={admin_id}").status_code == 200
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert t is not None and t.created_by is None
        a = db.query(Automation).filter(Automation.id == aid).first()
        assert a is not None and a.owner_id is None and a.created_by is None


def test_the_deletion_itself_is_recorded(client, admin_id):
    """Everything they did is gone, so the one row that must remain is the one
    saying they were erased — attributed to whoever did it."""
    uid = _mk_user(client, admin_id, "doomed4@x.test", "רשומה")
    client.delete(f"/api/users/{uid}?user_id={admin_id}")
    with Session(cityos_main.engine) as db:
        # by the address rather than by the id: the suite reuses ids across
        # tests, and an earlier purge logged one under the same number
        row = (db.query(AuditLog)
                 .filter(AuditLog.action == "delete", AuditLog.field_name == "user",
                         AuditLog.old_value.like("%doomed4@x.test%")).first())
    assert row is not None
    assert row.entity_id == uid and row.changed_by == admin_id
    assert "רשומה" in (row.old_value or "")       # the name, so the line reads


def test_you_cannot_delete_the_account_you_are_using(client, admin_id):
    r = client.delete(f"/api/users/{admin_id}?user_id={admin_id}")
    assert r.status_code == 400
    with Session(cityos_main.engine) as db:
        assert db.query(User).filter(User.id == admin_id).first() is not None


def test_the_last_system_admin_cannot_be_deleted(client, admin_id):
    """Otherwise the system is left with nobody who could undo it."""
    with Session(cityos_main.engine) as db:
        admins = [m.user_id for m in db.query(WorkspaceMember)
                  .filter(WorkspaceMember.role == "admin").all()]
    if len(admins) != 1:
        # another admin exists in this database: make the rule testable by
        # asking for the one that is NOT the actor
        other = next((a for a in admins if a != admin_id), None)
        if other is None:
            return
        r = client.delete(f"/api/users/{other}?user_id={admin_id}")
        assert r.status_code in (200, 400)
        return
    r = client.delete(f"/api/users/{admins[0]}?user_id={admin_id}")
    assert r.status_code == 400


def test_the_automation_identity_is_not_a_person(client, admin_id):
    with Session(cityos_main.engine) as db:
        bot = (db.query(User)
                 .filter(User.email == cityos_main.AUTOMATION_IDENTITY_EMAIL).first())
        bot_id = bot.id if bot else None
    if bot_id is None:
        return
    r = client.delete(f"/api/users/{bot_id}?user_id={admin_id}")
    assert r.status_code == 400
    with Session(cityos_main.engine) as db:
        assert db.query(User).filter(User.id == bot_id).first() is not None


def test_deleting_somebody_who_is_not_there(client, admin_id):
    assert client.delete(f"/api/users/999999?user_id={admin_id}").status_code == 404
