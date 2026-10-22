"""Group — פעולות מושהות: a wait that survives, re-checks, and can be called off.

  · the wait is stored with the item, the version of the rule, the event that
    started it and the moment it may come back;
  · at that moment the data is read again and the conditions asked again —
    dynamic values are recomputed, but the old and new value stay the ones the
    SOURCE event carried;
  · a condition that has changed skips it; a deleted item or a lost permission
    cancels it, and says so;
  · pausing a rule freezes what is waiting (or cancels it, if asked), and
    switching the rule back on re-checks;
  · an error-suspension freezes them; deleting the rule cancels them, after
    being told how many;
  · editing a rule does not move what is already waiting.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AutomationQueue, AutomationRun, Comment, Task

UTC = timezone.utc


def _board(client, admin_id, name="לוח המתנות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _member(client, admin_id, bid, uid, role="editor"):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    assert r.status_code == 200, r.text


def _col(client, bid, admin_id, **spec):
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    col = {"id": "col_" + spec["type"][:5] + str(len(cols)), **spec}
    cols.append(col)
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    assert r.status_code == 200, r.text
    return col


def _waiting_rule(client, bid, admin_id, after=None, config=None, **extra):
    """A rule that does something, waits, then does something else."""
    cfg = {"a_priority": "high",
           "actions": [{"key": "wait", "values": {"days": 60}}]
                      + (after or [{"key": "post_update", "values": {"text": "אחרי"}}])}
    cfg.update(config or {})
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "created_set_priority", "config": cfg, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title="פריט", **extra):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **extra}).json()["id"]


def _queued(bid, state=None):
    with Session(cityos_main.engine) as db:
        rows = db.query(AutomationQueue).filter(AutomationQueue.board_id == bid).all()
        return [r for r in rows if state is None or (r.state or "pending") == state]


def _due_now(bid):
    """Bring every waiting row's moment forward to now."""
    with Session(cityos_main.engine) as db:
        for r in db.query(AutomationQueue).filter(AutomationQueue.board_id == bid,
                                                  AutomationQueue.done_at == None).all():
            r.event = {**(r.event or {}),
                       "after": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
            r.resume_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        db.commit()


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]


def _said(tid):
    with Session(cityos_main.engine) as db:
        return [c.content for c in db.query(Comment).filter(Comment.task_id == tid).all()]


# ── what the wait remembers ────────────────────────────────────────────────

def test_a_wait_is_stored_with_everything_it_needs_to_come_back(client, admin_id):
    bid = _board(client, admin_id, "לוח זיכרון המתנה")
    a = _waiting_rule(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    rows = _queued(bid)
    assert len(rows) == 1
    r = rows[0]
    assert r.task_id == tid                        # which item
    assert r.automation_id == a["id"]              # which rule
    assert r.version == 1                          # and which version of it
    assert r.state == "pending"
    assert r.resume_at is not None                 # when it may come back
    assert (r.event or {}).get("type") == "resume"
    assert (r.event or {}).get("source") == "create", r.event   # the source event
    # where in the rule it stopped: the recipe's own action is the first, the
    # wait the second, so what is left starts at the third
    assert (r.event or {}).get("from") == 2


def test_the_wait_survives_a_restart(client, admin_id):
    """Durable storage, not memory: the row is in the database and the drain
    that finishes it reads it from there."""
    bid = _board(client, admin_id, "לוח עמידות")
    _waiting_rule(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        assert db.query(AutomationQueue).filter(AutomationQueue.task_id == tid).count() == 1
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _said(tid) == ["אחרי"]


# ── what it reads when it comes back ───────────────────────────────────────

def test_dynamic_values_are_worked_out_when_it_comes_back(client, admin_id):
    bid = _board(client, admin_id, "לוח ערך מחדש")
    _waiting_rule(client, bid, admin_id,
                  after=[{"key": "post_update", "values": {"text": "שם: {{item.name}}"}}])
    tid = _item(client, bid, admin_id, "שם ישן")
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "title": "שם חדש"})
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _said(tid) == ["שם: שם חדש"], _said(tid)


def test_the_old_and_new_value_stay_the_ones_the_event_carried(client, admin_id):
    """"ערכים דינמיים מחושבים מחדש, אך הערך הקודם והחדש נשארים לפי אירוע
    המקור" — they are what happened, not what the item says a week later."""
    bid = _board(client, admin_id, "לוח ערך קודם")
    cfg = {"t_status": "done",
           "actions": [{"key": "wait", "values": {"days": 60}},
                       {"key": "post_update",
                        "values": {"text": "היה {{event.old}} והפך ל-{{event.new}}"}}]}
    client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                json={"recipe_id": "status_set_priority",
                      "config": {**cfg, "a_priority": "high"}})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    # the item moves on while the rule waits
    client.patch(f"/api/tasks/{tid}", json={"status": "in_progress", "user_id": admin_id})
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    said = _said(tid)
    assert said and "והפך ל-done" in said[0], said


def test_a_condition_that_has_changed_skips_it(client, admin_id):
    """"תנאי שהשתנה גורם לדילוג" — the rest of the rule was promised about the
    item it was, and this is not that item any more."""
    bid = _board(client, admin_id, "לוח תנאי שהשתנה")
    c = _col(client, bid, admin_id, type="text", title="אזור")
    _waiting_rule(client, bid, admin_id,
                  config={"conditions": [{"kind": "column_is",
                                          "value": {"col": c["id"], "type": "text",
                                                    "op": "eq", "value": "צפון"}}]})
    tid = _item(client, bid, admin_id, custom_fields={c["id"]: "צפון"})
    assert _queued(bid, "pending"), "the wait was never made"
    client.patch(f"/api/tasks/{tid}",
                 json={"user_id": admin_id, "custom_fields": {c["id"]: "דרום"}})
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _said(tid) == [], "it ran on an item the condition no longer holds for"
    skipped = [r for r in _runs(client, bid, admin_id)
               if "המשך מושהה דולג" in (r["reason"] or "")]
    assert skipped, [r["reason"] for r in _runs(client, bid, admin_id)]


def test_a_condition_that_still_holds_lets_it_through(client, admin_id):
    bid = _board(client, admin_id, "לוח תנאי שנשאר")
    c = _col(client, bid, admin_id, type="text", title="אזור")
    _waiting_rule(client, bid, admin_id,
                  config={"conditions": [{"kind": "column_is",
                                          "value": {"col": c["id"], "type": "text",
                                                    "op": "eq", "value": "צפון"}}]})
    tid = _item(client, bid, admin_id, custom_fields={c["id"]: "צפון"})
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _said(tid) == ["אחרי"]


# ── what calls it off ──────────────────────────────────────────────────────

def test_a_deleted_item_cancels_it_and_the_log_says_so(client, admin_id):
    bid = _board(client, admin_id, "לוח פריט שנמחק")
    _waiting_rule(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    rows = _queued(bid)
    assert rows[0].state == "cancelled" and "הפריט נמחק" in (rows[0].note or "")
    assert any("המשך מושהה בוטל" in (r["reason"] or "") for r in _runs(client, bid, admin_id))


def test_a_lost_permission_cancels_it_and_the_log_says_so(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח הרשאה שאבדה")
    _member(client, admin_id, bid, guinea_id)
    _waiting_rule(client, bid, admin_id,
                  after=[{"key": "notify_person",
                          "values": {"person": {"kind": "user", "value": guinea_id}}}])
    _item(client, bid, admin_id)
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    rows = _queued(bid)
    assert rows[0].state == "cancelled", (rows[0].state, rows[0].note)
    assert any("המשך מושהה בוטל" in (r["reason"] or "") for r in _runs(client, bid, admin_id))


# ── a rule somebody stopped ────────────────────────────────────────────────

def test_pausing_a_rule_freezes_what_is_waiting(client, admin_id):
    bid = _board(client, admin_id, "לוח הקפאה")
    a = _waiting_rule(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "paused"})
    assert [r.state for r in _queued(bid)] == ["frozen"]
    # frozen is held, not spent: the drain leaves it alone
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _said(tid) == []
    assert [r.state for r in _queued(bid)] == ["frozen"]


def test_switching_it_back_on_lets_them_go_and_re_checks(client, admin_id):
    """"הפעלה מחדש מחייבת בדיקה חוזרת" — the re-check is what the resume does:
    the item, the conditions and the permissions are all read again."""
    bid = _board(client, admin_id, "לוח חזרה")
    a = _waiting_rule(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "paused"})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "active"})
    assert [r.state for r in _queued(bid)] == ["pending"]
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _said(tid) == ["אחרי"]


def test_pausing_can_cancel_them_instead_if_that_is_what_is_asked(client, admin_id):
    bid = _board(client, admin_id, "לוח ביטול בהשהיה")
    a = _waiting_rule(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"status": "paused", "pending": "cancel"})
    rows = _queued(bid)
    assert rows[0].state == "cancelled" and "בוטלו" in (rows[0].note or "")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "active"})
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _said(tid) == [], "a cancelled wait came back"


def test_an_error_suspension_freezes_them(client, admin_id, guinea_id):
    """"השהיה עקב שגיאה מקפיאה הפעלות ממתינות" — held rather than cancelled:
    the rule is broken, not wrong."""
    bid = _board(client, admin_id, "לוח השהיה עקב שגיאה")
    _member(client, admin_id, bid, guinea_id)
    a = _waiting_rule(client, bid, admin_id)
    _item(client, bid, admin_id, "ראשון")
    assert [r.state for r in _queued(bid)] == ["pending"]
    # the rule breaks on the NEXT item and is suspended
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        row.config = {**row.config, "a_priority": "no_such_priority"}
        db.commit()
    _item(client, bid, admin_id, "שני")
    with Session(cityos_main.engine) as db:
        assert db.query(Automation).filter(
            Automation.id == a["id"]).first().status == "paused_error"
    assert all(r.state == "frozen" for r in _queued(bid)), [r.state for r in _queued(bid)]


# ── deleting the rule ──────────────────────────────────────────────────────

def test_deleting_a_rule_with_waiting_runs_asks_first(client, admin_id):
    bid = _board(client, admin_id, "לוח מחיקה עם ממתינות")
    a = _waiting_rule(client, bid, admin_id)
    _item(client, bid, admin_id)
    r = client.delete(f"/api/automations/{a['id']}?user_id={admin_id}")
    assert r.status_code == 409, r.text
    body = r.json()["detail"]
    assert body["pending"] == 1 and body["needs"] == "cancel_pending"
    assert _queued(bid)[0].state == "pending", "it was cancelled without being asked"


def test_and_cancels_them_once_it_is_confirmed(client, admin_id):
    bid = _board(client, admin_id, "לוח מחיקה מאושרת")
    a = _waiting_rule(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    r = client.delete(f"/api/automations/{a['id']}?cancel_pending=true&user_id={admin_id}")
    assert r.status_code == 200, r.text
    rows = _queued(bid)
    assert rows[0].state == "cancelled" and "נמחקה" in (rows[0].note or "")
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _said(tid) == []


def test_a_rule_with_nothing_waiting_deletes_as_it_always_did(client, admin_id):
    bid = _board(client, admin_id, "לוח מחיקה רגילה")
    a = _waiting_rule(client, bid, admin_id)
    assert client.delete(f"/api/automations/{a['id']}?user_id={admin_id}").status_code == 200


# ── a rule edited while something of it waits ──────────────────────────────

def test_editing_a_rule_does_not_move_what_is_already_waiting(client, admin_id):
    """"הן ממשיכות לפי הגרסה שבה נוצרו" — a wait is a promise about what was
    going to happen, and a rule edited in the meantime did not change it."""
    bid = _board(client, admin_id, "לוח עריכה תוך המתנה")
    a = _waiting_rule(client, bid, admin_id,
                      after=[{"key": "post_update", "values": {"text": "הנוסח המקורי"}}])
    tid = _item(client, bid, admin_id)
    # the rule is rewritten and the new wording put into force
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"config": {"a_priority": "high",
                                  "actions": [{"key": "wait", "values": {"days": 60}},
                                              {"key": "post_update",
                                               "values": {"text": "הנוסח החדש"}}]}})
    client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}")
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _said(tid) == ["הנוסח המקורי"], _said(tid)
    assert any("לפי הגרסה שבה נוצרה ההמתנה" in (r["reason"] or "")
               for r in _runs(client, bid, admin_id))


def test_a_wait_made_after_the_edit_uses_the_new_wording(client, admin_id):
    bid = _board(client, admin_id, "לוח נוסח חדש")
    a = _waiting_rule(client, bid, admin_id,
                      after=[{"key": "post_update", "values": {"text": "ישן"}}])
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"config": {"a_priority": "high",
                                  "actions": [{"key": "wait", "values": {"days": 60}},
                                              {"key": "post_update",
                                               "values": {"text": "חדש"}}]}})
    client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}")
    tid = _item(client, bid, admin_id)             # created AFTER the edit
    _due_now(bid)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _said(tid) == ["חדש"], _said(tid)


# ── an emergency stop over the board ───────────────────────────────────────

def test_an_emergency_stop_holds_a_waiting_run_rather_than_spending_it(client, admin_id):
    bid = _board(client, admin_id, "לוח השבתה והמתנה")
    _waiting_rule(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    f = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "board", "board_id": bid, "reason": "חקירה"}).json()
    try:
        _due_now(bid)
        client.get(f"/api/boards/{bid}?user_id={admin_id}")
        assert _said(tid) == []
    finally:
        client.post(f"/api/admin/automations/release?user_id={admin_id}",
                    json={"freeze_id": f["freeze"]["id"]})
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _said(tid) == ["אחרי"], "the wait was lost to the stop instead of held"


# ── seeing what is waiting ─────────────────────────────────────────────────

def test_the_board_can_see_what_is_waiting_and_when(client, admin_id):
    bid = _board(client, admin_id, "לוח רשימת ממתינות")
    a = _waiting_rule(client, bid, admin_id, name="המתנה שלי")
    tid = _item(client, bid, admin_id, "פריט ממתין")
    d = client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}").json()
    w = d["waiting"]
    assert len(w) == 1, w
    assert w[0]["automation_id"] == a["id"] and w[0]["name"] == "המתנה שלי"
    assert w[0]["task_id"] == tid and w[0]["task_title"] == "פריט ממתין"
    assert w[0]["state"] == "pending" and w[0]["version"] == 1
    assert w[0]["resume_at"]


def test_a_frozen_one_says_why(client, admin_id):
    bid = _board(client, admin_id, "לוח ממתינה קפואה")
    a = _waiting_rule(client, bid, admin_id)
    _item(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "paused"})
    w = client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}"
                   ).json()["waiting"]
    assert w[0]["state"] == "frozen" and "מושהית" in w[0]["note"]


def test_seeing_them_follows_the_viewing_permission(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח ממתינות פרטי")
    _member(client, admin_id, bid, member_id, "viewer")
    _waiting_rule(client, bid, admin_id)
    _item(client, bid, admin_id)
    assert client.get(f"/api/boards/{bid}/automations/queue?user_id={member_id}"
                      ).status_code == 403


def test_the_screen_asks_before_a_delete_takes_them(client):
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
           ).read_text(encoding="utf-8")
    assert "cancel_pending" in src and "needs==='cancel_pending'" in src
    assert "מחק ובטל אותן" in src
