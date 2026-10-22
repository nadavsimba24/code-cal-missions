"""Group — גורמים מפעילים ומקורות שינוי.

Every row of the trigger table, the two rules that govern when a change counts
as an event at all, and the mirror column that may be read but never listened
to.

  פריט      · נוצר, והועבר לקבוצה
  תת־פריט   · נוצר (and finishing, from 5.4)
  שדה       · ערך שדה השתנה
  סטטוס/אנשים · סטטוס השתנה; משתמש שויך או הוסר
  תאריך     · במועד, לפני ואחרי; והגיע והסטטוס אינו הושלם
  קישור     · קושר או נותק

  · a change is an event only if the business value really moved;
  · one action over many items is one event per item, under a shared batch id.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import automations as recipes
import main as cityos_main
from models import Automation, AutomationRun, Group, Notification, Task


def _board(client, admin_id, name="לוח טריגרים"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _member(client, admin_id, bid, uid, role="editor"):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    assert r.status_code == 200, r.text


def _add(client, bid, admin_id, recipe_id, config=None, **extra):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id, "config": config or {}, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title="פריט", **extra):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **extra}).json()["id"]


def _group(client, bid, admin_id, name):
    return client.post("/api/groups", json={"board_id": bid, "name": name,
                                            "actor_id": admin_id}).json()["id"]


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]


def _cols(client, bid, admin_id, extra):
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    cols += extra
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    assert r.status_code == 200, r.text


# ── פריט: הועבר לקבוצה ──────────────────────────────────────────────────────

def test_moving_an_item_into_a_group_is_an_event(client, admin_id):
    bid = _board(client, admin_id, "לוח העברה")
    target = _group(client, bid, admin_id, "הושלמו")
    _add(client, bid, admin_id, "moved_group_set_status",
         {"t_group": target, "a_status": "done"})
    tid = _item(client, bid, admin_id)
    r = client.post(f"/api/tasks/{tid}/move",
                    json={"group_id": target, "user_id": admin_id})
    assert r.status_code == 200, r.text
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) == "done"
    run = _runs(client, bid, admin_id)[0]
    assert run["event_type"] == "moved_to_group" and run["outcome"] == "ran"


def test_a_move_into_a_different_group_does_not_set_the_rule_off(client, admin_id):
    bid = _board(client, admin_id, "לוח קבוצה אחרת")
    watched, other = _group(client, bid, admin_id, "הושלמו"), _group(client, bid, admin_id, "אחר")
    _add(client, bid, admin_id, "moved_group_set_status",
         {"t_group": watched, "a_status": "done"})
    tid = _item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/move", json={"group_id": other, "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) != "done"


def test_moving_an_item_where_it_already_is_is_not_an_event(client, admin_id):
    """"שמירה חוזרת של אותו ערך לא תפעיל אוטומציה"."""
    bid = _board(client, admin_id, "לוח אותה קבוצה")
    target = _group(client, bid, admin_id, "הושלמו")
    _add(client, bid, admin_id, "moved_group_notify_assignees", {"t_group": target})
    tid = _item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/move", json={"group_id": target, "user_id": admin_id})
    before = len(_runs(client, bid, admin_id))
    client.post(f"/api/tasks/{tid}/move", json={"group_id": target, "user_id": admin_id})
    assert len(_runs(client, bid, admin_id)) == before, "a move to where it already was fired"


# ── a bulk move: one event each, one id between them ────────────────────────

def test_a_bulk_move_is_one_event_per_item_under_one_batch(client, admin_id):
    bid = _board(client, admin_id, "לוח העברה מרובה")
    target = _group(client, bid, admin_id, "הושלמו")
    _add(client, bid, admin_id, "moved_group_set_status",
         {"t_group": target, "a_status": "done"})
    ids = [_item(client, bid, admin_id, f"פריט {i}") for i in range(3)]
    r = client.post(f"/api/boards/{bid}/items/move",
                    json={"ids": ids, "group_id": target, "user_id": admin_id})
    assert r.status_code == 200, r.text
    batch = r.json()["batch_id"]
    assert batch

    runs = [x for x in _runs(client, bid, admin_id) if x["event_type"] == "moved_to_group"]
    assert len(runs) == 3, f"{len(runs)} rows for 3 items"
    assert {x["task_id"] for x in runs} == set(ids), "a row is missing an item"
    assert {x["batch_id"] for x in runs} == {batch}, "the batch id is not shared"
    assert {x["source"] for x in runs} == {"bulk"}
    with Session(cityos_main.engine) as db:
        for i in ids:
            assert cityos_main._st_of(db.query(Task).filter(Task.id == i).first()) == "done"


def test_an_item_already_in_the_target_group_gets_no_event_in_a_bulk_move(client, admin_id):
    bid = _board(client, admin_id, "לוח מרובה חלקי")
    target = _group(client, bid, admin_id, "הושלמו")
    _add(client, bid, admin_id, "moved_group_notify_assignees", {"t_group": target})
    already, moving = _item(client, bid, admin_id, "כבר שם"), _item(client, bid, admin_id, "זז")
    client.post(f"/api/tasks/{already}/move", json={"group_id": target, "user_id": admin_id})
    r = client.post(f"/api/boards/{bid}/items/move",
                    json={"ids": [already, moving], "group_id": target, "user_id": admin_id})
    assert r.json()["unchanged"] == [already]
    runs = [x for x in _runs(client, bid, admin_id)
            if x["event_type"] == "moved_to_group" and x["batch_id"]]
    assert [x["task_id"] for x in runs] == [moving], runs


def test_a_single_move_carries_no_batch(client, admin_id):
    """"הפרד מקור אירוע ומזהה batch" — a change that was not one of many has a
    source like any other and no batch at all."""
    bid = _board(client, admin_id, "לוח בודד")
    target = _group(client, bid, admin_id, "הושלמו")
    _add(client, bid, admin_id, "moved_group_notify_assignees", {"t_group": target})
    tid = _item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/move", json={"group_id": target, "user_id": admin_id})
    run = _runs(client, bid, admin_id)[0]
    assert run["source"] == "item" and run["batch_id"] == ""


# ── תת־פריט נוצר ────────────────────────────────────────────────────────────

def test_creating_a_subitem_is_an_event_on_the_parent(client, admin_id):
    bid = _board(client, admin_id, "לוח תת פריט נוצר")
    _add(client, bid, admin_id, "subitem_created_set_status", {"a_status": "in_progress"})
    parent = _item(client, bid, admin_id, "אב")
    client.post("/api/tasks", json={"board_id": bid, "title": "תת", "parent_id": parent,
                                    "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == parent).first()) \
            == "in_progress"
    run = _runs(client, bid, admin_id)[0]
    assert run["event_type"] == "subitem_created" and run["task_id"] == parent
    assert run["source"] == "create"


def test_an_ordinary_item_is_not_a_subitem(client, admin_id):
    bid = _board(client, admin_id, "לוח בלי תתי")
    _add(client, bid, admin_id, "subitem_created_set_status", {"a_status": "in_progress"})
    tid = _item(client, bid, admin_id)
    assert [x for x in _runs(client, bid, admin_id)
            if x["event_type"] == "subitem_created"] == []


# ── שדה: ערך שדה השתנה ──────────────────────────────────────────────────────

def test_a_column_value_changing_is_an_event(client, admin_id):
    bid = _board(client, admin_id, "לוח עמודות")
    _cols(client, bid, admin_id, [{"id": "col_txt", "type": "text", "title": "הערה"}])
    _add(client, bid, admin_id, "column_changed_set_status",
         {"t_column": "col_txt", "a_status": "done"})
    tid = _item(client, bid, admin_id)
    r = client.patch(f"/api/tasks/{tid}",
                     json={"user_id": admin_id, "custom_fields": {"col_txt": "משהו"}})
    assert r.status_code == 200, r.text
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) == "done"
    run = next(x for x in _runs(client, bid, admin_id) if x["event_type"] == "column_changed")
    assert run["outcome"] == "ran"


def test_saving_a_column_with_the_same_value_is_not_an_event(client, admin_id):
    """The rule of this whole section: "שינוי ייחשב אירוע רק אם הערך העסקי
    השתנה בפועל"."""
    bid = _board(client, admin_id, "לוח שמירה חוזרת")
    _cols(client, bid, admin_id, [{"id": "col_txt", "type": "text", "title": "הערה"}])
    _add(client, bid, admin_id, "column_changed_notify_assignees", {"t_column": "col_txt"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}",
                 json={"user_id": admin_id, "custom_fields": {"col_txt": "משהו"}})
    first = len([x for x in _runs(client, bid, admin_id) if x["event_type"] == "column_changed"])
    assert first == 1
    for _ in range(3):                      # the same value, saved again and again
        client.patch(f"/api/tasks/{tid}",
                     json={"user_id": admin_id, "custom_fields": {"col_txt": "משהו"}})
    again = len([x for x in _runs(client, bid, admin_id) if x["event_type"] == "column_changed"])
    assert again == first, f"{again - first} events for a value that did not change"


def test_a_change_in_another_column_does_not_set_it_off(client, admin_id):
    bid = _board(client, admin_id, "לוח שתי עמודות")
    _cols(client, bid, admin_id, [{"id": "col_a", "type": "text", "title": "א"},
                                  {"id": "col_b", "type": "text", "title": "ב"}])
    _add(client, bid, admin_id, "column_changed_set_status",
         {"t_column": "col_a", "a_status": "done"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}",
                 json={"user_id": admin_id, "custom_fields": {"col_b": "ערך"}})
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) != "done"


# ── a mirror is read, never listened to ─────────────────────────────────────

def test_a_mirror_column_is_not_offered_as_a_trigger(client, admin_id):
    far = _board(client, admin_id, "לוח יעד למראה")
    bid = _board(client, admin_id, "לוח עם מראה")
    _cols(client, bid, admin_id, [
        {"id": "col_link", "type": "connect", "title": "קישור",
         "connect": {"board_ids": [far], "multi": True}},
        {"id": "col_mir", "type": "mirror", "title": "סטטוס אצלם",
         "mirror_of": {"connect": "col_link", "field": "status"}}])
    assert "mirror" in cityos_main.AUTOMATION_UNWATCHABLE_COLUMNS
    assert "connect" in cityos_main.AUTOMATION_UNWATCHABLE_COLUMNS
    # the screen offers only what may be listened to
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
           ).read_text(encoding="utf-8")
    assert "['mirror','connect','formula'].includes(c.type)" in src


def test_a_mirror_cell_never_raises_an_event(client, admin_id):
    """Not even a skipped one. The mirror holds a value that lives on ANOTHER
    item, so there is no change here to report — it is not watched at all."""
    far = _board(client, admin_id, "יעד מראה שנייה")
    bid = _board(client, admin_id, "לוח מראה שנייה")
    _cols(client, bid, admin_id, [
        {"id": "col_link", "type": "connect", "title": "קישור",
         "connect": {"board_ids": [far], "multi": True}},
        {"id": "col_mir", "type": "mirror", "title": "סטטוס אצלם",
         "mirror_of": {"connect": "col_link", "field": "status"}},
        {"id": "col_txt", "type": "text", "title": "הערה"}])
    a = _add(client, bid, admin_id, "column_changed_notify_assignees",
             {"t_column": "col_txt"})
    with Session(cityos_main.engine) as db:
        db.query(Automation).filter(Automation.id == a["id"]).update(
            {Automation.config: {"t_column": "col_mir"}})
        db.commit()
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}",
                 json={"user_id": admin_id, "custom_fields": {"col_mir": "x"}})
    assert _runs(client, bid, admin_id) == []


def test_a_rule_pointed_at_a_mirror_cannot_be_switched_on(client, admin_id):
    """It cannot be built through the screen, so this is a stored row being
    activated — and the refusal says what to do with it instead."""
    far = _board(client, admin_id, "יעד מראה שלישית")
    bid = _board(client, admin_id, "לוח מראה שלישית")
    _cols(client, bid, admin_id, [
        {"id": "col_link", "type": "connect", "title": "קישור",
         "connect": {"board_ids": [far], "multi": True}},
        {"id": "col_mir", "type": "mirror", "title": "סטטוס אצלם",
         "mirror_of": {"connect": "col_link", "field": "status"}},
        {"id": "col_txt", "type": "text", "title": "הערה"}])
    a = _add(client, bid, admin_id, "column_changed_notify_assignees",
             {"t_column": "col_txt"}, status="paused")
    with Session(cityos_main.engine) as db:
        db.query(Automation).filter(Automation.id == a["id"]).update(
            {Automation.config: {"t_column": "col_mir"}})
        db.commit()
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                     json={"status": "active"})
    assert r.status_code == 400, r.text
    assert "כתנאי" in r.json()["detail"], r.text


def test_a_mirror_answers_a_condition_by_reading_the_linked_item(client, admin_id):
    """The other half of the sentence, working: the rule is held back by what
    the LINKED item says, which is what a mirror is for."""
    far = _board(client, admin_id, "יעד לתנאי מראה")
    bid = _board(client, admin_id, "לוח תנאי מראה")
    _cols(client, bid, admin_id, [
        {"id": "col_link", "type": "connect", "title": "קישור",
         "connect": {"board_ids": [far], "multi": True}},
        {"id": "col_mir", "type": "mirror", "title": "שם אצלם",
         "mirror_of": {"connect": "col_link", "field": "title"}}])
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "critical",
          "conditions": [{"kind": "column_is",
                          "value": {"col": "col_mir", "type": "mirror",
                                    "value": "הפריט הרחוק"}}]})
    linked = _item(client, far, admin_id, "הפריט הרחוק")
    other = _item(client, far, admin_id, "פריט אחר")
    hit = client.post("/api/tasks", json={"board_id": bid, "title": "מתאים",
                                          "user_id": admin_id,
                                          "custom_fields": {"col_link": [linked]}}
                      ).json()["id"]
    miss = client.post("/api/tasks", json={"board_id": bid, "title": "לא מתאים",
                                           "user_id": admin_id,
                                           "custom_fields": {"col_link": [other]}}
                       ).json()["id"]
    with Session(cityos_main.engine) as db:
        assert cityos_main._task_priority_key(
            db.query(Task).filter(Task.id == hit).first()) == "critical"
        assert cityos_main._task_priority_key(
            db.query(Task).filter(Task.id == miss).first()) != "critical"


def test_a_mirror_is_still_usable_as_a_condition(client, admin_id):
    """"ניתן להשתמש בערכה כתנאי בלבד" — the other half of the same sentence."""
    kinds = {c["kind"] for c in recipes.conditions_catalog()}
    assert "column_is" in kinds and "column_is_not" in kinds
    assert "mirror" in recipes.column_types().get("text", []) \
        or any("mirror" in v for v in recipes.column_types().values()), \
        recipes.column_types()


# ── סטטוס ואנשים ────────────────────────────────────────────────────────────

def test_removing_an_assignee_is_an_event_of_its_own(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח הסרת שיוך")
    _member(client, admin_id, bid, guinea_id, "editor")
    _add(client, bid, admin_id, "unassigned_set_status", {"a_status": "in_progress"})
    tid = _item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/assignees",
                json={"actor_id": admin_id, "user_id": guinea_id})
    assert [x for x in _runs(client, bid, admin_id)
            if x["event_type"] == "person_unassigned"] == []
    client.post(f"/api/tasks/{tid}/assignees",
                json={"actor_id": admin_id, "user_id": guinea_id, "action": "remove"})
    run = next(x for x in _runs(client, bid, admin_id)
               if x["event_type"] == "person_unassigned")
    assert run["outcome"] == "ran"


def test_removing_somebody_who_was_not_assigned_is_not_an_event(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח הסרה ריקה")
    _member(client, admin_id, bid, guinea_id, "editor")
    _add(client, bid, admin_id, "unassigned_set_status", {"a_status": "in_progress"})
    tid = _item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/assignees",
                json={"actor_id": admin_id, "user_id": guinea_id, "action": "remove"})
    assert [x for x in _runs(client, bid, admin_id)
            if x["event_type"] == "person_unassigned"] == []


def test_saving_the_same_status_again_is_not_an_event(client, admin_id):
    bid = _board(client, admin_id, "לוח סטטוס חוזר")
    _add(client, bid, admin_id, "status_notify_assignees", {"t_status": "done"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    first = len(_runs(client, bid, admin_id))
    for _ in range(3):
        client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert len(_runs(client, bid, admin_id)) == first


# ── תאריך: לפני ואחרי ───────────────────────────────────────────────────────

def _with_due(client, bid, admin_id, days, title="פריט"):
    when = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days)
    return _item(client, bid, admin_id, title, due_date=when.isoformat())


def _already_on_for(aid, days):
    """A rule that has been switched on for a while.

    "הפעלה תחול רק על אירועים חדשים ממועד ההפעלה" (5.2) holds here too: a due
    date that passed before the rule existed is not an event it gets to act on.
    A rule switched on a moment ago therefore has nothing in the past to find,
    which is correct and is why these tests age it first.
    """
    with Session(cityos_main.engine) as db:
        db.query(Automation).filter(Automation.id == aid).update(
            {Automation.activated_at:
             datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)})
        db.commit()


def test_a_rule_fires_the_named_number_of_days_before_the_date(client, admin_id):
    bid = _board(client, admin_id, "לוח לפני")
    _add(client, bid, admin_id, "due_near_notify_assignees",
         {"t_days": 3, "conditions": [{"kind": "status_is_not", "value": "done"}]})
    soon = _with_due(client, bid, admin_id, 1, "בעוד יום")
    far = _with_due(client, bid, admin_id, 30, "בעוד חודש")
    client.get(f"/api/boards/{bid}?user_id={admin_id}")      # the sweep runs on a read
    hit = {x["task_id"] for x in _runs(client, bid, admin_id)
           if x["event_type"] == "due_date_near"}
    assert soon in hit and far not in hit, hit


def test_a_rule_fires_the_named_number_of_days_after_it(client, admin_id):
    bid = _board(client, admin_id, "לוח אחרי")
    a = _add(client, bid, admin_id, "due_passed_set_priority",
             {"t_days": 7, "a_priority": "critical"})
    _already_on_for(a["id"], 60)
    late = _with_due(client, bid, admin_id, -10, "עבר מזמן")
    just = _with_due(client, bid, admin_id, -1, "עבר אתמול")
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    with Session(cityos_main.engine) as db:
        assert cityos_main._task_priority_key(
            db.query(Task).filter(Task.id == late).first()) == "critical"
        assert cityos_main._task_priority_key(
            db.query(Task).filter(Task.id == just).first()) != "critical"


def test_the_date_sweep_says_where_it_came_from(client, admin_id):
    bid = _board(client, admin_id, "לוח מקור תאריך")
    a = _add(client, bid, admin_id, "due_passed_set_priority",
             {"t_days": 0, "a_priority": "high"})
    _already_on_for(a["id"], 60)
    _with_due(client, bid, admin_id, -2)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    run = next(x for x in _runs(client, bid, admin_id) if x["event_type"] == "due_date_passed")
    assert run["source"] == "date" and run["batch_id"] == ""


def test_a_date_rule_fires_once_per_item(client, admin_id):
    bid = _board(client, admin_id, "לוח פעם אחת")
    a = _add(client, bid, admin_id, "due_passed_set_priority",
             {"t_days": 0, "a_priority": "high"})
    _already_on_for(a["id"], 60)
    _with_due(client, bid, admin_id, -2)
    for _ in range(3):
        client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert len([x for x in _runs(client, bid, admin_id)
                if x["event_type"] == "due_date_passed"]) == 1


# ── the envelope itself ─────────────────────────────────────────────────────

def test_every_run_says_where_its_change_came_from(client, admin_id):
    bid = _board(client, admin_id, "לוח מקורות")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    run = _runs(client, bid, admin_id)[0]
    assert run["source"] == "create", run


def test_what_a_rule_sets_off_is_the_engines_own_write(client, admin_id):
    """A cascade's source is the engine, whatever set the first rule off — and
    it stays inside the batch it was started by."""
    bid = _board(client, admin_id, "לוח מפל")
    target = _group(client, bid, admin_id, "הושלמו")
    _add(client, bid, admin_id, "moved_group_set_status",
         {"t_group": target, "a_status": "done"})
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    ids = [_item(client, bid, admin_id, f"פריט {i}") for i in range(2)]
    batch = client.post(f"/api/boards/{bid}/items/move",
                        json={"ids": ids, "group_id": target,
                              "user_id": admin_id}).json()["batch_id"]
    runs = _runs(client, bid, admin_id)
    cascaded = [x for x in runs if x["depth"] > 0]
    assert cascaded, "the second rule never ran"
    assert {x["source"] for x in cascaded} == {"automation"}
    assert {x["batch_id"] for x in cascaded} == {batch}, \
        "a cascade lost the batch it belonged to"


def test_an_unknown_source_is_not_taken_on_the_requests_word(client, admin_id):
    bid = _board(client, admin_id, "לוח מקור מזויף")
    _add(client, bid, admin_id, "status_notify_assignees", {"t_status": "done"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}",
                 json={"status": "done", "user_id": admin_id, "source": "מה שבא לי"})
    run = next(x for x in _runs(client, bid, admin_id) if x["event_type"] == "status_changes_to")
    assert run["source"] == "item", run["source"]


def test_the_trigger_table_is_covered(client, admin_id):
    """Every row of the specification's table has a trigger behind it."""
    have = set(recipes.TRIGGERS)
    for kind in ("item_created", "moved_to_group",          # פריט
                 "subitem_created", "subitem_done",          # תת־פריט
                 "column_changed",                            # שדה
                 "status_changes_to", "person_assigned", "person_unassigned",
                 "due_date_arrives", "due_date_near", "due_date_passed",
                 "link_added", "link_removed"):
        assert kind in have, kind
    # and each of them is reachable from the library
    ids = {t["trigger"] for t in recipes.catalog()}
    assert {"moved_to_group", "subitem_created", "column_changed",
            "person_unassigned", "due_date_near", "due_date_passed"} <= ids
