"""A date rule can wait for a date column of the board's own, not only תאריך יעד.

"כאשר מגיע תאריך היעד" could only ever mean the built-in date, so a board that
keeps the date that matters in a column of its own — "דד ליין לביצוע (למלאי)" —
could not say "כשמגיע הדד ליין, סמן את «חריגה מדד ליין» כ«בחריגה»" at all. The
rule now names the column under `t_date_col`; absent is the built-in date, so
every rule stored before this means what it meant.

Pinned here: the sweep fires on the named column and ignores the built-in date
beside it, a column that is not a date column is refused at the save, and the
rule reads back with the column's own title.
"""
from datetime import timedelta

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, Board, Task


def _board(client, uid, name):
    return client.post("/api/boards", json={"name": name, "user_id": uid}).json()["id"]


def _item(client, bid, uid, title="פריט", **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": uid, **kw}).json()["id"]


def _add_col(client, bid, uid, col):
    cols = client.get(f"/api/boards/{bid}").json()["columns"]
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": uid, "columns": cols + [col]})
    assert r.status_code == 200, r.text


def _age(rid):
    # a date rule only acts on moments after it was switched on, so the rule
    # is aged and the dates below are in the past
    with Session(cityos_main.engine) as db:
        db.query(Automation).filter(Automation.id == rid).update(
            {Automation.activated_at: cityos_main._now_naive() - timedelta(days=60)})
        db.commit()


def _status(tid):
    with Session(cityos_main.engine) as db:
        return cityos_main._task_status_key(db.query(Task).filter(Task.id == tid).first())


def _drop(bid):
    with Session(cityos_main.engine) as db:
        db.query(Automation).filter(Automation.board_id == bid).delete()
        db.query(Task).filter(Task.board_id == bid).delete()
        db.query(Board).filter(Board.id == bid).delete()
        db.commit()


def test_the_rule_fires_when_the_named_date_column_arrives_and_not_on_the_due_date(
        client, admin_id):
    bid = _board(client, admin_id, "דד ליין בעמודה")
    try:
        _add_col(client, bid, admin_id,
                 {"id": "col_deadline", "type": "date", "title": "דד ליין לביצוע"})
        r = client.post(f"/api/boards/{bid}/automations",
                        json={"actor_id": admin_id, "recipe_id": "due_set_status",
                              "config": {"a_status": "done", "t_date_col": "col_deadline"}})
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        assert (r.json().get("config") or {}).get("t_date_col") == "col_deadline", r.json()
        _age(rid)
        past = (cityos_main._now_naive() - timedelta(days=2)).date().isoformat()
        future = (cityos_main._now_naive() + timedelta(days=30)).date().isoformat()
        # the column's day has come; the built-in date has not
        hit = _item(client, bid, admin_id, "הגיע", due_date=future + "T00:00:00",
                    custom_fields={"col_deadline": past})
        # the built-in date has come; the column's day has not — not this rule's
        miss = _item(client, bid, admin_id, "לא הגיע", due_date=past + "T00:00:00",
                     custom_fields={"col_deadline": future})
        client.get(f"/api/boards/{bid}?user_id={admin_id}")
        assert _status(hit) == "done", "the rule did not fire on the column it names"
        assert _status(miss) != "done", "the rule fired on the built-in date instead"
    finally:
        _drop(bid)


def test_a_rule_naming_a_column_that_is_not_a_date_is_refused(client, admin_id):
    bid = _board(client, admin_id, "לא עמודת תאריך")
    try:
        _add_col(client, bid, admin_id, {"id": "col_txt", "type": "text", "title": "טקסט"})
        r = client.post(f"/api/boards/{bid}/automations",
                        json={"actor_id": admin_id, "recipe_id": "due_set_status",
                              "config": {"a_status": "done", "t_date_col": "col_txt"}})
        assert r.status_code == 400, r.text
    finally:
        _drop(bid)


def test_the_catalog_offers_a_date_column_on_the_date_triggers(client, admin_id):
    import automations as recipes
    for rid in ("due_set_status", "due_notify_assignees"):
        parts = recipes._sentence_parts(recipes.recipe(rid))
        assert parts["trigger_col_kind"] == "date", parts
        assert "{t_date_col}" in parts["trigger_col"], parts
