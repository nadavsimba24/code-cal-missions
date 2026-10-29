"""קבוצה — האוטומציות שהקטלוג לא ידע לבטא.

Four rules a person showed us from monday, and what each of them needed here:

  · "When «לקוחות» changes, set value to …" — "עדכן את העמודה" has been an
    ACTION since columns could be written, and had no recipe of its own. It
    could only be bolted onto a rule built around something else, so a rule
    about nothing but a column was not a rule this catalog could express.
  · "When an item is created, set value to …" — the same gap, another trigger.
  · "Every 7 days, if «קבלת מסמכים» has passed and «סטטוס ההליך» is …, notify
    …" — every part of that existed except the clock. Every trigger here was
    something that HAPPENED to an item; none of them was the passage of time,
    so a chase that comes round again could not be written at all.

The clock has no scheduler behind it — nothing in this product does. A
recurring rule is swept when the board is read, which makes it "the first time
somebody opens the board after the interval elapsed". That is the promise every
other timed rule here already makes, and these pin that it is kept: once per
interval, not once per board-read, and never backfilled.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

import automations as recipes
import main as cityos_main
from models import Automation, Notification, Task


def _board(client, admin_id, name="לוח מתכונים חסרים", invite=None):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    if invite is not None:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": invite, "role": "editor"})
    return bid


def _col(client, bid, admin_id, **col):
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [col]})
    assert r.status_code == 200, r.text
    return r.json()["columns"][0]


def _cols(client, bid, admin_id, cols):
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": cols})
    assert r.status_code == 200, r.text
    return r.json()["columns"]


def _item(client, bid, admin_id, title="פריט", fields=None):
    body = {"board_id": bid, "title": title, "user_id": admin_id}
    if fields:
        body["custom_fields"] = fields
    return client.post("/api/tasks", json=body).json()["id"]


def _add(client, bid, admin_id, recipe_id, config, active=True):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config, "is_active": active})


def _cell(tid, col_id):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        return (t.custom_fields or {}).get(col_id)


def _notes(tid, uid):
    with Session(cityos_main.engine) as db:
        return [n for n in db.query(Notification)
                .filter(Notification.task_id == tid).all() if n.user_id == uid]


def _age_rule(aid, days):
    """Backdate the rule's activation, which is the clock a recurring rule
    counts from. The alternative is a test that takes a week."""
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == aid).first()
        a.activated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        db.commit()


def _open(client, bid, admin_id):
    """Reading the board is what runs the timed rules — there is no scheduler."""
    client.get(f"/api/boards/{bid}?user_id={admin_id}")


# ── "עדכן את העמודה" as a rule of its own ──────────────────────────────────

def test_a_column_change_can_write_another_column(client, admin_id):
    """The screenshot's "When «לקוחות» changes, set value to …"."""
    bid = _board(client, admin_id)
    src, dst = _cols(client, bid, admin_id,
                     [{"type": "text", "title": "לקוחות"},
                      {"type": "text", "title": "מנהל פרויקט מקומי"}])
    r = _add(client, bid, admin_id, "column_changed_set_column",
             {"t_column": src["id"], "a_column": dst["id"], "a_text": "רונית"})
    assert r.status_code == 200, r.text
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}",
                 json={"custom_fields": {src["id"]: "עיריית חולון"}})
    assert _cell(tid, dst["id"]) == "רונית"


def test_a_new_item_can_have_a_column_filled_in(client, admin_id):
    """And "When an item is created, set value to …"."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="text", title="מנהל פרויקט מקומי")
    _add(client, bid, admin_id, "created_set_column",
         {"a_column": col["id"], "a_text": "רונית"})
    assert _cell(_item(client, bid, admin_id), col["id"]) == "רונית"


def test_a_status_change_can_write_a_column(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="text", title="הערה")
    _add(client, bid, admin_id, "status_set_column",
         {"t_status": "done", "a_column": col["id"], "a_text": "הסתיים"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    assert _cell(tid, col["id"]) == "הסתיים"


def test_a_column_rule_is_unavailable_until_there_is_one_to_write(client, admin_id):
    """It is listed and marked, not quietly dropped — the library's own rule.

    "A column" is not the right question for an action that WRITES one. Every
    board is issued מזהה פריט, מועד יצירה and יוצר הרשומה on creation; all
    three are derived from the item and store nothing, so a board holding only
    those has a column to listen to and none to write.
    """
    bid = _board(client, admin_id, "לוח בלי עמודות")
    lib = lambda: client.get(f"/api/boards/{bid}/automations/templates"
                             f"?user_id={admin_id}").json()["templates"]
    one = next(t for t in lib() if t["id"] == "created_set_column")
    assert one["available"] is False
    assert one["missing"] == [recipes.NEEDS_HE["writable_column"]], one["missing"]
    # the system columns it was issued with are not what it was asking for
    _col(client, bid, admin_id, type="text", title="הערה")
    assert next(t for t in lib() if t["id"] == "created_set_column")["available"] is True


def test_a_rule_cannot_write_a_column_the_board_derives(client, admin_id):
    """מועד יצירה is read off the item, so a cell written for it is a value the
    board never looks at. The rule says so rather than reporting success."""
    bid = _board(client, admin_id, "לוח שדות מערכת")
    made = _col(client, bid, admin_id, type="created_at", title="מועד יצירה")
    a = _add(client, bid, admin_id, "created_set_column",
             {"a_column": made["id"], "a_text": "2026-01-01"}).json()
    tid = _item(client, bid, admin_id)
    assert _cell(tid, made["id"]) is None
    runs = client.get(f"/api/boards/{bid}/automations/runs"
                      f"?user_id={admin_id}&automation_id={a['id']}").json()["runs"]
    assert runs and runs[0]["outcome"] == "skipped", runs
    assert "אינה ניתנת לעדכון" in runs[0]["reason"], runs[0]["reason"]


# ── כל כמה ימים ────────────────────────────────────────────────────────────

def test_a_recurring_rule_does_not_fire_in_the_interval_it_was_switched_on(
        client, admin_id, guinea_id):
    """A rule turned on at nine in the morning must not notify everybody about
    everything at nine in the morning. The first firing is one whole interval
    later, which is what "כל 7 ימים" says."""
    bid = _board(client, admin_id, invite=guinea_id)
    _add(client, bid, admin_id, "every_days_notify_person",
         {"t_days": 7, "a_person": {"kind": "user", "value": guinea_id}})
    tid = _item(client, bid, admin_id)
    _open(client, bid, admin_id)
    assert not _notes(tid, guinea_id)


def test_and_fires_once_the_interval_has_elapsed(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "every_days_notify_person",
               {"t_days": 7, "a_person": {"kind": "user", "value": guinea_id}}).json()["id"]
    tid = _item(client, bid, admin_id)
    _age_rule(aid, 8)
    _open(client, bid, admin_id)
    assert len(_notes(tid, guinea_id)) == 1


def test_opening_the_board_again_does_not_chase_twice(client, admin_id, guinea_id):
    """Once per interval, not once per board-read. Without the ledger this
    would notify on every refresh, which is the one failure a chase cannot
    have."""
    bid = _board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "every_days_notify_person",
               {"t_days": 7, "a_person": {"kind": "user", "value": guinea_id}}).json()["id"]
    tid = _item(client, bid, admin_id)
    _age_rule(aid, 8)
    for _ in range(4):
        _open(client, bid, admin_id)
    assert len(_notes(tid, guinea_id)) == 1


def test_the_next_interval_chases_again(client, admin_id, guinea_id):
    """The point of a recurring rule: it comes round."""
    bid = _board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "every_days_notify_person",
               {"t_days": 7, "a_person": {"kind": "user", "value": guinea_id}}).json()["id"]
    tid = _item(client, bid, admin_id)
    _age_rule(aid, 8)
    _open(client, bid, admin_id)
    _age_rule(aid, 15)                     # a second interval has gone by
    _open(client, bid, admin_id)
    assert len(_notes(tid, guinea_id)) == 2


def test_a_board_nobody_opened_for_a_month_is_not_backfilled(client, admin_id, guinea_id):
    """Three reminders arriving together are not three reminders anybody
    wanted. The interval that has come round is one interval, however many
    went by unread."""
    bid = _board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "every_days_notify_person",
               {"t_days": 7, "a_person": {"kind": "user", "value": guinea_id}}).json()["id"]
    tid = _item(client, bid, admin_id)
    _age_rule(aid, 30)
    _open(client, bid, admin_id)
    assert len(_notes(tid, guinea_id)) == 1


def test_a_paused_rule_chases_nobody(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "every_days_notify_person",
               {"t_days": 7, "a_person": {"kind": "user", "value": guinea_id}},
               active=False).json()["id"]
    tid = _item(client, bid, admin_id)
    _age_rule(aid, 30)
    _open(client, bid, admin_id)
    assert not _notes(tid, guinea_id)


def test_an_interval_of_nothing_is_refused(client, admin_id):
    """There is no scheduler, so the sweep is a board read — "כל 0 ימים" would
    be "on every read"."""
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "every_days_notify_assignees", {"t_days": 0}).json()
    assert a["config"]["t_days"] == recipes.MIN_EVERY_DAYS
    # the due-date distances keep their zero: there, it is the date itself
    b = _add(client, bid, admin_id, "due_near_notify_assignees",
             {"t_days": 0, "a_status": "done"}).json()
    assert b["config"]["t_days"] == 0


# ── the whole of the first rule in the screenshot ──────────────────────────

def test_the_weekly_chase_from_the_screenshot(client, admin_id, guinea_id):
    """כל 7 ימים, רק אם «קבלת מסמכים» לפני היום וגם «סטטוס ההליך» הוא «קבלת
    טפסים מהרשות» — שלח התראה.

    The clock was the only piece missing; a date column asked "before today"
    and a status column asked for one of its own options were both already
    here. This is the four of them together.
    """
    bid = _board(client, admin_id, invite=guinea_id)
    got, step = _cols(client, bid, admin_id, [
        {"type": "date", "title": "קבלת מסמכים"},
        {"type": "status", "title": "סטטוס ההליך",
         "options": [{"label": "קבלת טפסים מהרשות"}, {"label": "הסתיים"}]}])
    waiting = next(o for o in step["options"] if o["label"] == "קבלת טפסים מהרשות")
    done = next(o for o in step["options"] if o["label"] == "הסתיים")
    conds = [{"kind": "column_is",
              "value": {"col": got["id"], "type": "date", "op": "before", "value": "today"}},
             {"kind": "column_is",
              "value": {"col": step["id"], "type": "status", "value": "קבלת טפסים מהרשות"}}]
    r = _add(client, bid, admin_id, "every_days_notify_person",
             {"t_days": 7, "a_person": {"kind": "user", "value": guinea_id},
              "conditions": conds})
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    assert "כל «7» ימים" in r.json()["sentence"], r.json()["sentence"]

    past = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    future = (datetime.now(timezone.utc) + timedelta(days=9)).strftime("%Y-%m-%d")
    cell = lambda o: {"id": o["id"], "label": o["label"], "color": o.get("color")}
    chase = _item(client, bid, admin_id, "ממתין לרשות",
                  {got["id"]: past, step["id"]: cell(waiting)})
    not_due = _item(client, bid, admin_id, "עוד לא",
                    {got["id"]: future, step["id"]: cell(waiting)})
    finished = _item(client, bid, admin_id, "נגמר",
                     {got["id"]: past, step["id"]: cell(done)})

    _age_rule(aid, 8)
    _open(client, bid, admin_id)
    assert len(_notes(chase, guinea_id)) == 1, "the item being waited on was not chased"
    assert not _notes(not_due, guinea_id), "an item whose date has not passed was chased"
    assert not _notes(finished, guinea_id), "a finished item was chased"
