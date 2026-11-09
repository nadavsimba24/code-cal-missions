"""Deleting a rule settles every table that names it — the way Postgres insists.

A board admin pressing מחק on QA got "לא ניתן למחוק" and the rule stayed. The
permission check had passed; the DELETE itself was failing. Ten tables carry an
`automation_id`, and the route detached only one of them — the run log — so the
statement left nine tables pointing at a row that was going away.

Nothing caught it, because referential integrity is not enforced in the place
the suite runs. SQLite ignores a foreign key unless the connection asks for it
with PRAGMA foreign_keys=ON, and neither the developer's database nor this
suite did; the deployed app is Postgres (DATABASE_URL), which always enforces
them. So the delete "worked" everywhere a test could see and 500'd in the one
place a person could.

These tests therefore turn the pragma ON for the length of the test, which is
what makes them stand in for production at all. What they pin: the delete
succeeds with the children present, the history outlives the rule detached from
it, and the rule's own rows go with it.
"""
import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session
import main as cityos_main
from models import (Automation, AutomationQueue, AutomationRun, AutomationVersion,
                    AutomationTestRun, AutomationActionExecution)


def _as(uid):
    return {"X-CityOS-User": str(uid)}


def _fk_on(dbapi_con, _rec):
    cur = dbapi_con.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@pytest.fixture
def strict_fks():
    """SQLite with its foreign keys enforced, as the deployed Postgres is.

    The pool has to be emptied on the way in and on the way out: the pragma is
    per CONNECTION, so a connection handed out before the listener was added
    would not have it, and one handed back with it would carry it into every
    test that follows.
    """
    event.listen(cityos_main.engine, "connect", _fk_on)
    cityos_main.engine.dispose()
    with Session(cityos_main.engine) as db:
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    try:
        yield
    finally:
        event.remove(cityos_main.engine, "connect", _fk_on)
        cityos_main.engine.dispose()


def _board_with_a_rule(client, admin_id):
    bid = client.post("/api/boards",
                      json={"name": "לוח מחיקת כלל", "user_id": admin_id}).json()["id"]
    aid = client.post(f"/api/boards/{bid}/automations",
                      json={"recipe_id": "created_set_priority",
                            "config": {"a_priority": "high"}},
                      headers=_as(admin_id)).json()["id"]
    return bid, aid


def test_a_rule_with_a_version_behind_it_deletes(client, admin_id, strict_fks):
    """Every saved rule has at least one version row, and that column is NOT
    NULL — so this is the case every single delete on QA was hitting."""
    bid, aid = _board_with_a_rule(client, admin_id)
    try:
        with Session(cityos_main.engine) as db:
            assert db.query(AutomationVersion).filter(
                AutomationVersion.automation_id == aid).count() >= 1
        r = client.delete(f"/api/automations/{aid}", headers=_as(admin_id))
        assert r.status_code == 200, r.text
        with Session(cityos_main.engine) as db:
            assert db.query(Automation).filter(Automation.id == aid).first() is None
            assert db.query(AutomationVersion).filter(
                AutomationVersion.automation_id == aid).count() == 0
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_what_the_rule_did_outlives_it(client, admin_id, strict_fks):
    """The run log keeps its rows, detached — each already carries the sentence
    and the item's title, so the history reads with no rule behind it."""
    bid, aid = _board_with_a_rule(client, admin_id)
    try:
        gid = client.get(f"/api/boards/{bid}").json()["groups"][0]["id"]
        client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "פריט שהכלל נגע בו", "user_id": admin_id})
        with Session(cityos_main.engine) as db:
            ran = db.query(AutomationRun).filter(AutomationRun.automation_id == aid).count()
        assert ran >= 1, "the rule should have fired on the new item"

        assert client.delete(f"/api/automations/{aid}",
                             headers=_as(admin_id)).status_code == 200
        with Session(cityos_main.engine) as db:
            assert db.query(AutomationRun).filter(
                AutomationRun.automation_id == aid).count() == 0
            kept = (db.query(AutomationRun)
                      .filter(AutomationRun.board_id == bid,
                              AutomationRun.automation_id.is_(None)).all())
            assert len(kept) >= ran
            assert any((k.sentence or "") for k in kept), "a detached run still says what ran"
            assert all((k.recipe_id or "") for k in kept)
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_a_test_run_goes_with_the_rule_it_tested(client, admin_id, strict_fks):
    """A "בדיקה על פריט" is a working note about the rule, not a record of the
    board — it has nothing left to say once the rule is gone."""
    bid, aid = _board_with_a_rule(client, admin_id)
    try:
        gid = client.get(f"/api/boards/{bid}").json()["groups"][0]["id"]
        tid = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                              "title": "פריט", "user_id": admin_id}).json()["id"]
        r = client.post(f"/api/automations/{aid}/test", json={"task_id": tid},
                        headers=_as(admin_id))
        assert r.status_code == 200, r.text
        with Session(cityos_main.engine) as db:
            assert db.query(AutomationTestRun).filter(
                AutomationTestRun.automation_id == aid).count() >= 1

        assert client.delete(f"/api/automations/{aid}",
                             headers=_as(admin_id)).status_code == 200
        with Session(cityos_main.engine) as db:
            assert db.query(AutomationTestRun).filter(
                AutomationTestRun.automation_id == aid).count() == 0
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_nothing_is_left_pointing_at_the_rule(client, admin_id, strict_fks):
    """The general form of it: after the delete, no table names that id.

    Written as a sweep rather than a list so a table added later is covered by
    it — the failure this is about was one table nobody remembered.
    """
    bid, aid = _board_with_a_rule(client, admin_id)
    try:
        gid = client.get(f"/api/boards/{bid}").json()["groups"][0]["id"]
        tid = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                              "title": "פריט", "user_id": admin_id}).json()["id"]
        client.post(f"/api/automations/{aid}/test", json={"task_id": tid},
                    headers=_as(admin_id))
        assert client.delete(f"/api/automations/{aid}",
                             headers=_as(admin_id)).status_code == 200
        with Session(cityos_main.engine) as db:
            for model in (cityos_main.AUTOMATION_HISTORY_TABLES
                          + cityos_main.AUTOMATION_OWN_TABLES):
                left = db.query(model).filter(model.automation_id == aid).count()
                assert left == 0, f"{model.__tablename__} still names the deleted rule"
            # and the per-action analytics the history keeps are still addressable
            db.query(AutomationActionExecution).filter(
                AutomationActionExecution.board_id == bid).count()
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_a_wait_that_was_called_off_is_still_there_to_read(client, admin_id, strict_fks):
    """Deleting a rule cancels what it had waiting, and that cancellation is
    the one thing somebody comes looking for afterwards — so the queue row
    stays, detached and marked, rather than going with the rule."""
    bid = client.post("/api/boards",
                      json={"name": "לוח המתנה שבוטלה", "user_id": admin_id}).json()["id"]
    try:
        cfg = {"a_priority": "high",
               "actions": [{"key": "wait", "values": {"days": 60}},
                           {"key": "post_update", "values": {"text": "אחרי"}}]}
        aid = client.post(f"/api/boards/{bid}/automations",
                          json={"recipe_id": "created_set_priority", "config": cfg},
                          headers=_as(admin_id)).json()["id"]
        gid = client.get(f"/api/boards/{bid}").json()["groups"][0]["id"]
        client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "פריט ממתין", "user_id": admin_id})
        with Session(cityos_main.engine) as db:
            assert db.query(AutomationQueue).filter(
                AutomationQueue.automation_id == aid).count() == 1

        # it refuses until it is told to cancel them, and says how many
        r = client.delete(f"/api/automations/{aid}", headers=_as(admin_id))
        assert r.status_code == 409 and r.json()["detail"]["pending"] == 1
        r = client.delete(f"/api/automations/{aid}?cancel_pending=true",
                          headers=_as(admin_id))
        assert r.status_code == 200, r.text

        with Session(cityos_main.engine) as db:
            rows = db.query(AutomationQueue).filter(
                AutomationQueue.board_id == bid).all()
            assert len(rows) == 1, "the cancelled wait went with the rule"
            assert rows[0].automation_id is None
            assert rows[0].state == "cancelled" and "נמחקה" in (rows[0].note or "")
            assert rows[0].done_at is not None, "a detached wait the drain could pick up"
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")
