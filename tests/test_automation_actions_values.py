"""Group — פעולות וערכים דינמיים.

  · the MVP action table: update or clear a field, assign and unassign, make an
    item and a sub-item, move a group, say something, notify, link, update a
    linked item, and wait;
  · values taken from the item rather than typed into the rule — and a value
    that does not fit the target field is not written;
  · who a notification goes to, what it says, and what it may not say.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import automations as recipes
import main as cityos_main
from models import Automation, AutomationQueue, Comment, Group, Notification, Task, User


def _board(client, admin_id, name="לוח פעולות"):
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


def _add(client, bid, admin_id, recipe_id="created_set_priority", config=None, **extra):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id,
                             "config": config or {"a_priority": "high"}, **extra})


def _acts(client, bid, admin_id, actions, recipe="created_set_priority",
          config=None, **extra):
    cfg = dict(config or {"a_priority": "high"})
    cfg["actions"] = actions
    return _add(client, bid, admin_id, recipe, cfg, **extra)


def _item(client, bid, admin_id, title="פריט", **extra):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **extra}).json()["id"]


def _task(tid):
    with Session(cityos_main.engine) as db:
        return db.query(Task).filter(Task.id == tid).first()


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]


def _notes(uid):
    with Session(cityos_main.engine) as db:
        return db.query(Notification).filter(Notification.user_id == uid,
                                             Notification.type == "automation").all()


# ── the action table ───────────────────────────────────────────────────────

def test_the_mvp_action_table_is_all_there(client):
    have = set(recipes.ACTIONS)
    for key in ("set_column", "clear_column",          # עדכון או ניקוי ערך
                "assign_person", "unassign_person",    # שיוך או הסרת אחראי
                "create_item", "create_subitem", "move_to_group",
                "post_update", "notify_person",
                "link_to_item", "copy_to_linked",
                "wait"):
        assert key in have, key
    # and every one of them is in the grant, with what it writes declared
    for key in have:
        assert key in cityos_main.AUTOMATION_GRANTED_ACTIONS, key
        assert key in cityos_main.AUTOMATION_ACTION_FIELDS, key


def test_a_rule_can_update_a_column(client, admin_id):
    bid = _board(client, admin_id, "לוח עדכון עמודה")
    c = _col(client, bid, admin_id, type="text", title="הערה")
    r = _acts(client, bid, admin_id,
              [{"key": "set_column", "values": {"column": c["id"], "text": "טופל"}}])
    assert r.status_code == 200, r.text
    tid = _item(client, bid, admin_id)
    assert (_task(tid).custom_fields or {}).get(c["id"]) == "טופל"


def test_a_rule_can_clear_one(client, admin_id):
    bid = _board(client, admin_id, "לוח ניקוי עמודה")
    c = _col(client, bid, admin_id, type="text", title="הערה")
    _acts(client, bid, admin_id,
          [{"key": "clear_column", "values": {"column": c["id"]}}])
    tid = _item(client, bid, admin_id, custom_fields={c["id"]: "ישן"})
    assert (_task(tid).custom_fields or {}).get(c["id"]) in (None, "")


def test_clearing_an_empty_column_is_a_skip_and_says_so(client, admin_id):
    bid = _board(client, admin_id, "לוח ניקוי ריק")
    c = _col(client, bid, admin_id, type="text", title="הערה")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "clear_column", "values": {"column": c["id"]}}]})
    _item(client, bid, admin_id)
    runs = _runs(client, bid, admin_id)
    assert "ריקה כבר" in (runs[0]["reason"] or ""), runs[0]


def test_a_value_that_does_not_fit_the_column_is_not_written(client, admin_id):
    """"ערך שאינו מתאים לסוג שדה היעד לא יישמר" — and the history says so."""
    bid = _board(client, admin_id, "לוח ערך לא מתאים")
    c = _col(client, bid, admin_id, type="number", title="תקציב")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "set_column",
                       "values": {"column": c["id"], "text": "הרבה"}}]})
    tid = _item(client, bid, admin_id)
    assert (_task(tid).custom_fields or {}).get(c["id"]) is None
    runs = _runs(client, bid, admin_id)
    assert "אינו מספר" in (runs[0]["reason"] or ""), runs[0]


def test_a_number_that_does_fit_is_written_as_a_number(client, admin_id):
    bid = _board(client, admin_id, "לוח מספר תקין")
    c = _col(client, bid, admin_id, type="number", title="תקציב")
    _acts(client, bid, admin_id,
          [{"key": "set_column", "values": {"column": c["id"], "text": "1500"}}])
    tid = _item(client, bid, admin_id)
    assert (_task(tid).custom_fields or {}).get(c["id"]) == 1500


def test_a_mirror_is_never_written_to(client, admin_id):
    far = _board(client, admin_id, "יעד למראה פעולה")
    bid = _board(client, admin_id, "לוח כתיבה למראה")
    _col(client, bid, admin_id, type="connect", title="קישור",
         connect={"board_ids": [far], "multi": True})
    m = _col(client, bid, admin_id, type="mirror", title="מראה",
             mirror_of={"connect": "col_conne0", "field": "title"})
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "set_column", "values": {"column": m["id"], "text": "x"}}]})
    _item(client, bid, admin_id)
    assert "אינה ניתנת לעדכון" in (_runs(client, bid, admin_id)[0]["reason"] or "")


def test_a_rule_can_take_an_assignee_off(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח הסרת שיוך")
    _member(client, admin_id, bid, guinea_id)
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "high",
          "actions": [{"key": "unassign_person", "values": {"person": guinea_id}}]})
    tid = _item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/assignees",
                json={"actor_id": admin_id, "user_id": guinea_id})
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert guinea_id not in {u.id for u in t.assignees}


def test_a_rule_can_make_an_item_on_its_own_board(client, admin_id):
    bid = _board(client, admin_id, "לוח יצירת פריט")
    gid = client.post("/api/groups", json={"board_id": bid, "name": "נכנסים",
                                           "actor_id": admin_id}).json()["id"]
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "high",
          "actions": [{"key": "create_item",
                       "values": {"text": "משימת המשך", "group": gid}}]})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == bid,
                                     Task.title == "משימת המשך").first()
        assert made is not None and made.group_id == gid


# ── a wait between two actions ─────────────────────────────────────────────

def test_a_wait_is_between_a_minute_and_thirty_days(client, admin_id):
    bid = _board(client, admin_id, "לוח המתנה")
    for bad in (0, -5, recipes.MAX_WAIT_DAYS * 24 * 60 + 1):
        r = _acts(client, bid, admin_id, [{"key": "wait", "values": {"days": bad}}])
        assert r.status_code == 400, bad
    assert _acts(client, bid, admin_id,
                 [{"key": "wait", "values": {"days": 60}}]).status_code == 200


def test_what_comes_after_a_wait_waits(client, admin_id):
    bid = _board(client, admin_id, "לוח אחרי המתנה")
    c = _col(client, bid, admin_id, type="text", title="הערה")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "wait", "values": {"days": 60}},
                      {"key": "set_column",
                       "values": {"column": c["id"], "text": "אחרי"}}]})
    tid = _item(client, bid, admin_id)
    # the first action ran, the one after the wait has not
    assert cityos_main._task_priority_key(_task(tid)) == "high"
    assert (_task(tid).custom_fields or {}).get(c["id"]) is None
    with Session(cityos_main.engine) as db:
        q = db.query(AutomationQueue).filter(AutomationQueue.board_id == bid,
                                             AutomationQueue.done_at == None).all()
        assert len(q) == 1 and (q[0].event or {}).get("type") == "resume"
    runs = _runs(client, bid, admin_id)
    assert "ממתינות" in (runs[0]["reason"] or ""), runs[0]


def test_a_wait_that_is_over_comes_back_and_finishes_the_rule(client, admin_id):
    bid = _board(client, admin_id, "לוח המתנה שהסתיימה")
    c = _col(client, bid, admin_id, type="text", title="הערה")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "wait", "values": {"days": 60}},
                      {"key": "set_column",
                       "values": {"column": c["id"], "text": "אחרי"}}]})
    tid = _item(client, bid, admin_id)
    # its moment arrives
    with Session(cityos_main.engine) as db:
        row = db.query(AutomationQueue).filter(AutomationQueue.board_id == bid,
                                               AutomationQueue.done_at == None).first()
        row.event = {**row.event,
                     "after": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
        db.commit()
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert (_task(tid).custom_fields or {}).get(c["id"]) == "אחרי"
    assert any("המשך אחרי המתנה" in (r["reason"] or "") for r in _runs(client, bid, admin_id))


def test_a_wait_whose_item_is_gone_does_not_bring_the_queue_down(client, admin_id):
    bid = _board(client, admin_id, "לוח המתנה פריט נמחק")
    c = _col(client, bid, admin_id, type="text", title="הערה")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "wait", "values": {"days": 60}},
                      {"key": "set_column",
                       "values": {"column": c["id"], "text": "אחרי"}}]})
    tid = _item(client, bid, admin_id)
    client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
    with Session(cityos_main.engine) as db:
        row = db.query(AutomationQueue).filter(AutomationQueue.board_id == bid,
                                               AutomationQueue.done_at == None).first()
        row.event = {**row.event,
                     "after": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
        db.commit()
    assert client.get(f"/api/boards/{bid}?user_id={admin_id}").status_code == 200
    with Session(cityos_main.engine) as db:
        assert db.query(AutomationQueue).filter(
            AutomationQueue.board_id == bid, AutomationQueue.done_at == None).count() == 0


# ── values taken from the item ─────────────────────────────────────────────

def test_a_name_can_be_built_from_the_item(client, admin_id):
    bid = _board(client, admin_id, "לוח ערכים דינמיים")
    gid = client.post("/api/groups", json={"board_id": bid, "name": "המשך",
                                           "actor_id": admin_id}).json()["id"]
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "high",
          "actions": [{"key": "create_item",
                       "values": {"text": "המשך ל-{{item.name}} ב{{board.name}}",
                                  "group": gid}}]})
    tid = _item(client, bid, admin_id, "תיקון מדרכה")
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        titles = [t.title for t in db.query(Task).filter(Task.board_id == bid).all()]
    assert "המשך ל-תיקון מדרכה בלוח ערכים דינמיים" in titles, titles


def test_a_field_of_the_item_can_be_used(client, admin_id):
    bid = _board(client, admin_id, "לוח ערך משדה")
    c = _col(client, bid, admin_id, type="text", title="אזור")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "post_update",
                       "values": {"text": "האזור הוא {{field." + c["id"] + "}}"}}]})
    tid = _item(client, bid, admin_id, custom_fields={c["id"]: "צפון"})
    with Session(cityos_main.engine) as db:
        said = [x.content for x in db.query(Comment).filter(Comment.task_id == tid).all()]
    assert said == ["האזור הוא צפון"], said


def test_a_value_that_is_missing_becomes_nothing_and_not_the_word_none(client, admin_id):
    bid = _board(client, admin_id, "לוח ערך חסר")
    c = _col(client, bid, admin_id, type="text", title="אזור")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "post_update",
                       "values": {"text": "האזור: {{field." + c["id"] + "}}."}}]})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        said = [x.content for x in db.query(Comment).filter(Comment.task_id == tid).all()]
    assert said == ["האזור: ."], said
    assert "None" not in said[0]


def test_the_person_who_made_the_change_and_the_time_are_available(client, admin_id):
    bid = _board(client, admin_id, "לוח מי ומתי")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "high",
          "actions": [{"key": "post_update",
                       "values": {"text": "שונה בידי {{actor.name}} ב-{{now.date}}"}}]})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        said = db.query(Comment).filter(Comment.task_id == tid).first().content
        me = db.query(User.name).filter(User.id == admin_id).scalar()
    assert me in said and datetime.now().strftime("%d/%m/%Y") in said


def test_an_unknown_value_is_refused_where_the_rule_is_written(client, admin_id):
    """A typo in a token is a value that silently never appears — the hardest
    kind of mistake to see in a rule that otherwise works."""
    bid = _board(client, admin_id, "לוח ערך לא מוכר")
    r = _acts(client, bid, admin_id,
              [{"key": "post_update", "values": {"text": "שלום {{item.nmae}}"}}])
    assert r.status_code == 400 and "ערך דינמי לא מוכר" in r.json()["detail"]


def test_a_value_from_a_linked_item_answers_only_when_there_is_one(client, admin_id):
    far = _board(client, admin_id, "יעד לערך מקושר")
    bid = _board(client, admin_id, "מקור לערך מקושר")
    _col(client, bid, admin_id, type="connect", title="קישור",
         connect={"board_ids": [far], "multi": True})
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "high",
          "actions": [{"key": "post_update",
                       "values": {"text": "מקושר ל-[{{linked.col_conne0.name}}]"}}]})
    one = _item(client, far, admin_id, "הפריט האחד")
    two = _item(client, far, admin_id, "ועוד אחד")

    alone = _item(client, bid, admin_id, custom_fields={"col_conne0": [one]})
    client.patch(f"/api/tasks/{alone}", json={"status": "done", "user_id": admin_id})
    both = _item(client, bid, admin_id, custom_fields={"col_conne0": [one, two]})
    client.patch(f"/api/tasks/{both}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        said = {c.task_id: c.content for c in db.query(Comment).all()}
    assert said.get(alone) == "מקושר ל-[הפריט האחד]"
    assert said.get(both) == "מקושר ל-[]", "three linked items are not one value"


# ── who a notification goes to ─────────────────────────────────────────────

def test_the_five_kinds_of_recipient_are_offered(client):
    assert set(recipes.RECIPIENTS) == {"user", "field", "actor", "owner", "board_admin"}
    assert all(r["label"] for r in recipes.recipients_catalog())


def test_a_notification_can_go_to_whoever_made_the_change(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח נמען מבצע")
    _member(client, admin_id, bid, guinea_id)
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": "done", "a_person": {"kind": "actor"}})
    tid = _item(client, bid, admin_id)
    before = len(_notes(guinea_id))
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": guinea_id})
    assert len(_notes(guinea_id)) == before + 1


def test_a_notification_can_go_to_the_people_in_a_column(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח נמען מעמודה")
    _member(client, admin_id, bid, guinea_id)
    c = _col(client, bid, admin_id, type="people", title="מלווה")
    _add(client, bid, admin_id, "created_notify_person",
         {"a_person": {"kind": "field", "value": c["id"]}})
    before = len(_notes(guinea_id))
    _item(client, bid, admin_id, custom_fields={c["id"]: [guinea_id]})
    assert len(_notes(guinea_id)) == before + 1


def test_a_notification_can_go_to_the_board_s_managers(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח נמען מנהלים")
    _member(client, admin_id, bid, guinea_id, "admin")
    _add(client, bid, admin_id, "created_notify_person",
         {"a_person": {"kind": "board_admin"}})
    before = len(_notes(guinea_id))
    _item(client, bid, admin_id)
    assert len(_notes(guinea_id)) == before + 1


def test_a_notification_can_go_to_the_rule_s_owner(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח נמען בעלים")
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id, "created_notify_person",
             {"a_person": {"kind": "owner"}}).json()
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"owner_id": guinea_id})
    before = len(_notes(guinea_id))
    _item(client, bid, admin_id)
    assert len(_notes(guinea_id)) == before + 1


def test_an_empty_recipient_skips_the_notification_and_says_so(client, admin_id):
    """"אם שדה הנמען ריק, ברירת המחדל היא דילוג על ההתראה ורישום בלוג" — not an
    error, and not everybody."""
    bid = _board(client, admin_id, "לוח נמען ריק")
    c = _col(client, bid, admin_id, type="people", title="מלווה")
    _add(client, bid, admin_id, "created_notify_person",
         {"a_person": {"kind": "field", "value": c["id"]}})
    _item(client, bid, admin_id)
    runs = _runs(client, bid, admin_id)
    assert runs and runs[0]["outcome"] == "skipped"
    assert "אין נמען" in (runs[0]["reason"] or ""), runs[0]
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.board_id == bid).first()
        assert a.status == "active", "an empty recipient stopped the rule"


def test_a_recipient_who_may_not_open_the_item_is_not_told_about_it(client, admin_id,
                                                                     guinea_id):
    bid = _board(client, admin_id, "לוח נמען חסום")
    _member(client, admin_id, bid, guinea_id)
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": "done", "a_person": {"kind": "user", "value": guinea_id}})
    tid = _item(client, bid, admin_id, "פריט סודי")
    client.post(f"/api/tasks/{tid}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"})
    before = len(_notes(guinea_id))
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert len(_notes(guinea_id)) == before
    assert "הרשאה" in (_runs(client, bid, admin_id)[0]["reason"] or "")


# ── what a notification says ───────────────────────────────────────────────

def test_a_notification_carries_the_five_things_it_must(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח תוכן התראה")
    _member(client, admin_id, bid, guinea_id)
    _add(client, bid, admin_id, "created_notify_person",
         {"a_person": {"kind": "user", "value": guinea_id}}, name="התראת פתיחה")
    tid = _item(client, bid, admin_id, "תיקון מדרכה")
    note = _notes(guinea_id)[-1]
    body = note.body or ""
    assert "התראת פתיחה" in body                       # which rule
    assert "נוצר פריט" in body                          # what happened
    assert "תיקון מדרכה" in body                        # which item
    assert f"item={tid}" in body                        # and a way straight to it
    assert "לוח תוכן התראה" in body                     # which board
    assert datetime.now().strftime("%d/%m/%Y") in body  # and when


def test_a_notification_does_not_quote_the_values_the_rule_was_built_with(client,
                                                                           admin_id,
                                                                           guinea_id):
    """The rule's sentence names a person, and sometimes an item on another
    board. A recipient entitled to THIS item is not thereby entitled to those."""
    far = _board(client, admin_id, "לוח רחוק סודי")
    bid = _board(client, admin_id, "לוח מקור להתראה")
    _member(client, admin_id, bid, guinea_id)
    _col(client, bid, admin_id, type="connect", title="קישור",
         connect={"board_ids": [far], "multi": True})
    secret = _item(client, far, admin_id, "שם סודי מאוד")
    _add(client, bid, admin_id, "created_link_item",
         {"a_connect": "col_conne0", "a_item": secret,
          "actions": [{"key": "notify_person",
                       "values": {"person": {"kind": "user", "value": guinea_id}}}]},
         name="קישור ואז התראה")
    _item(client, bid, admin_id, "פריט רגיל")
    body = (_notes(guinea_id)[-1].body or "")
    assert "קישור ואז התראה" in body
    assert "שם סודי מאוד" not in body, body


# ── מיפוי שדות בין שני לוחות ───────────────────────────────────────────────

def _two_boards(client, admin_id, name):
    far = _board(client, admin_id, name + " יעד")
    bid = _board(client, admin_id, name)
    _col(client, bid, admin_id, type="connect", title="קישור",
         connect={"board_ids": [far], "multi": True})
    return far, bid, "col_conne0"


def _mapped(client, bid, admin_id, far, link, mapping, group=None, text="פריט ממופה"):
    gid = group or client.post("/api/groups", json={"board_id": far, "name": "נכנסים",
                                                    "actor_id": admin_id}).json()["id"]
    # the carrying rule sets a STATUS, so the priority the mapping moves is the
    # item's own and not something this rule wrote a line earlier
    return gid, _acts(client, bid, admin_id,
                      [{"key": "create_mapped_and_link",
                        "values": {"connect": link, "board": far, "target_group": gid,
                                   "text": text, "map": mapping}}],
                      recipe="created_set_status", config={"a_status": "in_progress"})


def test_a_mapping_carries_the_fields_it_names(client, admin_id):
    far, bid, link = _two_boards(client, admin_id, "לוח מיפוי")
    a = _col(client, bid, admin_id, type="text", title="אזור")
    b = _col(client, far, admin_id, type="text", title="אזור היעד")
    gid, r = _mapped(client, bid, admin_id, far, link,
                     [{"from": a["id"], "to": b["id"]},
                      {"from": "priority", "to": "priority"}])
    assert r.status_code == 200, r.text
    _item(client, bid, admin_id, "מקור", priority="critical",
          custom_fields={a["id"]: "צפון"})
    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == far,
                                     Task.title == "פריט ממופה").first()
        assert made is not None, "no item was created"
        assert (made.custom_fields or {}).get(b["id"]) == "צפון"
        assert cityos_main._task_priority_key(made) == "critical"
        assert made.group_id == gid


def test_a_mapping_between_types_that_cannot_carry_each_other_is_refused(client, admin_id):
    """"המערכת תאפשר מיפוי רק בין סוגי שדות תואמים"."""
    far, bid, link = _two_boards(client, admin_id, "לוח מיפוי שגוי")
    a = _col(client, bid, admin_id, type="date", title="תאריך")
    b = _col(client, far, admin_id, type="number", title="מספר")
    _, r = _mapped(client, bid, admin_id, far, link, [{"from": a["id"], "to": b["id"]}])
    assert r.status_code == 400, r.text
    assert "תואם" in r.json()["detail"], r.json()


def test_a_mapping_naming_a_field_that_is_not_there_is_refused(client, admin_id):
    far, bid, link = _two_boards(client, admin_id, "לוח מיפוי חסר")
    _, r = _mapped(client, bid, admin_id, far, link,
                   [{"from": "col_nope", "to": "title"}])
    assert r.status_code == 400 and "אינו קיים" in r.json()["detail"]


def test_a_mapping_may_not_write_one_target_twice(client, admin_id):
    far, bid, link = _two_boards(client, admin_id, "לוח מיפוי כפול")
    a = _col(client, bid, admin_id, type="text", title="א")
    b = _col(client, bid, admin_id, type="text", title="ב")
    _, r = _mapped(client, bid, admin_id, far, link,
                   [{"from": a["id"], "to": "title"}, {"from": b["id"], "to": "title"}])
    assert r.status_code == 400 and "פעמיים" in r.json()["detail"]


def test_an_empty_mapping_is_refused(client, admin_id):
    far, bid, link = _two_boards(client, admin_id, "לוח מיפוי ריק")
    _, r = _mapped(client, bid, admin_id, far, link, [])
    assert r.status_code == 400 and "מיפוי" in r.json()["detail"]


def test_a_mapping_that_breaks_later_stops_the_rule_before_it_fires(client, admin_id):
    """"מיפוי חסר או בלתי תקין יוצג לפני ההפעלה וימנע את הפעלת האוטומציה" — a
    column can be deleted under a rule that was right when it was written."""
    far, bid, link = _two_boards(client, admin_id, "לוח מיפוי שנשבר")
    a = _col(client, bid, admin_id, type="text", title="אזור")
    b = _col(client, far, admin_id, type="text", title="אזור היעד")
    _, r = _mapped(client, bid, admin_id, far, link, [{"from": a["id"], "to": b["id"]}])
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    # the target column goes
    cols = [c for c in client.get(f"/api/boards/{far}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_") and c["id"] != b["id"]]
    client.patch(f"/api/boards/{far}?actor_id={admin_id}", json={"columns": cols})

    _item(client, bid, admin_id, "אחרי השבירה")
    runs = _runs(client, bid, admin_id)
    assert runs and runs[0]["outcome"] == "skipped"
    assert "מיפוי" in (runs[0]["reason"] or ""), runs[0]
    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == far,
                                     Task.title == "פריט ממופה").count()
    assert made == 0, "the item was created with a mapping that could not work"
    # and it cannot simply be switched back on
    client.patch(f"/api/automations/{rid}?user_id={admin_id}", json={"status": "paused"})
    on = client.patch(f"/api/automations/{rid}?user_id={admin_id}",
                      json={"status": "active"})
    assert on.status_code == 400 and "מיפוי" in on.json()["detail"], on.text
