"""Removing a demo user really removes them, references and all.

`REMOVED_DEMO_USERS` is the list of seeded accounts that should no longer exist
anywhere, and a startup step deletes them from databases that already have
them. It detached most of what points at a user and missed several — including
`Environment.created_by`, which did not exist until today. That gap is quiet on
SQLite, which does not enforce foreign keys unless asked, and fatal on
Postgres: one dangling reference makes the DELETE fail, `_safe_startup` logs it
and carries on, and the user stays. In production that is the difference
between "deleted" and "looks deleted".
"""
import itertools

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from models import (Automation, Board, BoardMember, BoardView, Environment,
                    EnvironmentMember, ItemLink, Notification, Task, User,
                    WorkspaceMember)
from conftest import ADMIN_ID

_seq = itertools.count(1)


@pytest.fixture
def demo_user(client, monkeypatch):
    """A user on the removal list, holding one of everything that points at a user."""
    n = next(_seq)
    name, email = f"דמו לבדיקה {n}", f"purge{n}@cityos.test"
    r = client.post("/api/users", json={"actor_id": ADMIN_ID, "name": name, "email": email,
                                        "role": "member"})
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    monkeypatch.setitem(cityos_main.REMOVED_DEMO_USERS, name, email)
    return uid


def _exists(uid):
    with Session(cityos_main.engine) as db:
        return db.query(User).filter(User.id == uid).first() is not None


def test_a_listed_user_is_deleted(client, demo_user):
    cityos_main._purge_removed_demo_users()
    assert not _exists(demo_user)


def test_every_reference_to_them_is_detached_first(client, demo_user):
    """The references the purge never handled — the reason it would fail."""
    uid = demo_user
    with Session(cityos_main.engine) as db:
        board = db.query(Board).first()
        env = db.query(Environment).first()
        task = db.query(Task).filter(Task.board_id == board.id).first()
        env.created_by = uid
        board.deleted_by = uid
        if task:
            task.deleted_by = uid
        db.add(EnvironmentMember(environment_id=env.id, user_id=uid, role="member"))
        db.add(BoardView(board_id=board.id, user_id=uid))
        db.add(Automation(board_id=board.id, recipe_id="status_changes",
                          created_by=uid, updated_by=uid))
        db.commit()
        env_id, board_id, task_id = env.id, board.id, (task.id if task else None)

    cityos_main._purge_removed_demo_users()

    assert not _exists(uid)
    with Session(cityos_main.engine) as db:
        assert db.query(Environment).filter(Environment.id == env_id).first().created_by is None
        assert db.query(Board).filter(Board.id == board_id).first().deleted_by is None
        if task_id:
            assert db.query(Task).filter(Task.id == task_id).first().deleted_by is None
        assert db.query(EnvironmentMember).filter(EnvironmentMember.user_id == uid).count() == 0
        assert db.query(BoardView).filter(BoardView.user_id == uid).count() == 0
        a = db.query(Automation).filter(Automation.board_id == board_id).order_by(Automation.id.desc()).first()
        assert a.created_by is None and a.updated_by is None


def test_their_memberships_go_with_them(client, demo_user):
    uid = demo_user
    with Session(cityos_main.engine) as db:
        db.add(BoardMember(board_id=db.query(Board).first().id, user_id=uid, role="editor"))
        db.add(Notification(user_id=uid, type="board_add", title="שלום"))
        db.commit()

    cityos_main._purge_removed_demo_users()
    with Session(cityos_main.engine) as db:
        assert db.query(BoardMember).filter(BoardMember.user_id == uid).count() == 0
        assert db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid).count() == 0
        assert db.query(Notification).filter(Notification.user_id == uid).count() == 0


def test_what_they_authored_survives_without_them(client, demo_user):
    """Their items and comments stay; only the name comes off."""
    uid = demo_user
    with Session(cityos_main.engine) as db:
        board = db.query(Board).first()
        t = Task(title="פריט של משתמש שנמחק", board_id=board.id, created_by=uid)
        db.add(t); db.commit(); tid = t.id

    cityos_main._purge_removed_demo_users()
    with Session(cityos_main.engine) as db:
        kept = db.query(Task).filter(Task.id == tid).first()
        assert kept is not None and kept.created_by is None


def test_the_last_administrator_is_never_deleted(client, monkeypatch):
    """A database with no administrator has no screen that can grant one."""
    with Session(cityos_main.engine) as db:
        admins = {m.user_id for m in db.query(WorkspaceMember)
                  .filter(WorkspaceMember.role == "admin").all()}
        admins |= {u.id for u in db.query(User).filter(User.role == "admin").all()}
        assert admins, "the suite should have at least one administrator"
        users = db.query(User).filter(User.id.in_(admins)).all()
        names = [(u.name, u.email) for u in users]
    for name, email in names:                      # list every one of them for removal
        monkeypatch.setitem(cityos_main.REMOVED_DEMO_USERS, name, email)

    cityos_main._purge_removed_demo_users()

    with Session(cityos_main.engine) as db:
        left = (db.query(WorkspaceMember).filter(WorkspaceMember.role == "admin").count()
                + db.query(User).filter(User.role == "admin").count())
    assert left >= 1, "the purge emptied the system of administrators"


def test_a_seeded_database_keeps_the_one_admin_it_has(client, monkeypatch):
    """This step runs before memberships exist, so asking only about
    WorkspaceMember would find no administrators at all and delete the only
    one there was — which is what a brand-new database is."""
    with Session(cityos_main.engine) as db:
        had = [m.user_id for m in db.query(WorkspaceMember)
               .filter(WorkspaceMember.role == "admin").all()]
        db.query(WorkspaceMember).filter(WorkspaceMember.role == "admin").delete(synchronize_session=False)
        db.commit()                                 # a freshly seeded database, before _seed_memberships
        sole = db.query(User).filter(User.role == "admin").first()
        assert sole is not None
        monkeypatch.setitem(cityos_main.REMOVED_DEMO_USERS, sole.name, sole.email)
        sole_id = sole.id
    try:
        cityos_main._purge_removed_demo_users()
        assert _exists(sole_id), "the only administrator was deleted before they could be granted a row"
    finally:
        # the suite shares one database; put the rows back or every later test
        # runs as somebody with no rights
        with Session(cityos_main.engine) as db:
            for uid in had:
                if not db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid).first():
                    db.add(WorkspaceMember(user_id=uid, role="admin"))
                else:
                    db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid).first().role = "admin"
            db.commit()


def test_a_user_not_on_the_list_is_left_alone(client):
    r = client.post("/api/users", json={"actor_id": ADMIN_ID, "name": "נשאר",
                                        "email": f"stays{next(_seq)}@cityos.test", "role": "member"})
    uid = r.json()["id"]
    cityos_main._purge_removed_demo_users()
    assert _exists(uid)
