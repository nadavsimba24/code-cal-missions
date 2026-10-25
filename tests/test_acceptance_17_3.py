"""סעיף 17.3 — בדיקות הקבלה, AC-01 עד AC-52.

One test per criterion, named by its id, each checking the expected result as
the table states it. Where an area already has deep coverage elsewhere, the
test here is still a direct check of the sentence in the table rather than a
pointer at another file: an acceptance run has to be readable on its own by
somebody holding the table.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
import automations as recipes
from models import (Automation, AutomationIncident, AutomationQueue, AutomationRun,
                    AuditLog, Board, Comment, EventOutbox, Notification, Task)

AS = lambda uid: {"X-CityOS-User": str(uid)}


# ── helpers ────────────────────────────────────────────────────────────────

def _board(client, uid, name):
    return client.post("/api/boards", json={"name": name, "user_id": uid}).json()["id"]


def _item(client, bid, uid, title="פריט", **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": uid, **kw}).json()["id"]


def _add(client, bid, uid, recipe_id="created_set_priority", config=None, **extra):
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": uid, "recipe_id": recipe_id,
                          "config": config or {"a_priority": "high"}, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _runs(client, bid, uid, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={uid}{qs}"
                      ).json()["runs"]


def _prio(tid):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        return cityos_main._task_priority_key(t) if t else None


def _status_of(rid):
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == rid).first()
        return a.status if a else None


def _col(client, bid, uid, **spec):
    cols = client.get(f"/api/boards/{bid}").json()["columns"]
    col = {"id": spec.pop("id", "col_" + spec["type"][:4] + str(len(cols))), **spec}
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": uid, "columns": cols + [col]})
    assert r.status_code == 200, r.text
    return col


def _two_boards(client, uid, tag):
    """A source board and an EMPTY target: every new board opens with three
    starter items, and counting "what the rule created" has to count that and
    nothing else."""
    a, b = _board(client, uid, f"מקור {tag}"), _board(client, uid, f"יעד {tag}")
    with Session(cityos_main.engine) as db:
        db.query(Task).filter(Task.board_id == b).delete()
        db.commit()
    cols = client.get(f"/api/boards/{a}").json()["columns"] + [
        {"type": "connect", "title": "קישור",
         "connect": {"board_ids": [b], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": uid, "columns": cols})
    c = next(x for x in client.get(f"/api/boards/{a}").json()["columns"]
             if x["type"] == "connect")
    return a, b, c


# ── AC-01 .. AC-10 ─────────────────────────────────────────────────────────

def test_AC_01_a_new_rule_is_active_and_only_catches_new_events(client, admin_id):
    bid = _board(client, admin_id, "AC01")
    before = _item(client, bid, admin_id, "קודם")
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "critical"})
    assert a["status"] == "active" and a["is_active"] is True
    assert _prio(before) != "critical", "it reached back at an item that predates it"
    after = _item(client, bid, admin_id, "אחרי")
    client.patch(f"/api/tasks/{after}", json={"status": "done", "user_id": admin_id})
    assert _prio(after) == "critical"


def test_AC_02_the_conditions_are_read_and_the_actions_run_once(client, admin_id):
    bid = _board(client, admin_id, "AC02")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "conditions": [{"kind": "priority_is", "value": "low"}]})
    tid = _item(client, bid, admin_id, priority="low")
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    ran = [r for r in _runs(client, bid, admin_id) if r["outcome"] == "ran"]
    assert len(ran) == 1, ran
    assert ((ran[0]["result"] or {}).get("conditions") or [])[0]["held"] is True


def test_AC_03_saving_the_same_value_again_does_nothing(client, admin_id):
    bid = _board(client, admin_id, "AC03")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    n = len(_runs(client, bid, admin_id))
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert len(_runs(client, bid, admin_id)) == n, "a no-op save fired the rule"


def test_AC_04_a_condition_that_fails_logs_a_skip_and_does_nothing(client, admin_id):
    bid = _board(client, admin_id, "AC04")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "conditions": [{"kind": "has_assignee", "value": True}]})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert _prio(tid) != "critical"
    r = _runs(client, bid, admin_id)[0]
    assert r["status"] == "skipped_condition" and r["reason"], r


def test_AC_05_several_actions_run_in_order(client, admin_id):
    bid = _board(client, admin_id, "AC05")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "post_update", "values": {"text": "שני"}},
                      {"key": "set_status", "values": {"status": "in_progress"}}]})
    tid = _item(client, bid, admin_id)
    steps = (_runs(client, bid, admin_id)[0]["result"] or {}).get("steps") or []
    assert [s["key"] for s in steps] == ["set_priority", "post_update", "set_status"]
    assert [s["index"] for s in steps] == [1, 2, 3]
    assert tid


def test_AC_06_deleting_a_field_suspends_and_notifies(client, admin_id):
    bid = _board(client, admin_id, "AC06")
    col = _col(client, bid, admin_id, type="text", title="אזור")
    rule = _add(client, bid, admin_id, "column_changed_notify_assignees",
                {"t_column": col["id"]})
    with Session(cityos_main.engine) as db:
        before = db.query(Notification).filter(Notification.user_id == admin_id,
                                               Notification.type == "automation").count()
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id,
                       "columns": [c for c in client.get(f"/api/boards/{bid}").json()["columns"]
                                   if c["id"] != col["id"]]})
    assert _status_of(rule["id"]) == "paused_error"
    with Session(cityos_main.engine) as db:
        assert db.query(Notification).filter(
            Notification.user_id == admin_id,
            Notification.type == "automation").count() > before


def test_AC_07_renaming_a_field_keeps_the_rule_and_shows_the_new_name(client, admin_id):
    bid = _board(client, admin_id, "AC07")
    col = _col(client, bid, admin_id, id="col_r", type="text", title="לפני")
    rule = _add(client, bid, admin_id, "column_changed_notify_assignees",
                {"t_column": col["id"]})
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id,
                       "columns": [dict(c, title="אחרי") if c["id"] == "col_r" else c
                                   for c in client.get(f"/api/boards/{bid}").json()["columns"]]})
    assert _status_of(rule["id"]) == "active"
    row = next(x for x in client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                                     ).json()["automations"] if x["id"] == rule["id"])
    assert "אחרי" in row["sentence"], row["sentence"]


def test_AC_08_losing_the_target_board_stops_the_write_and_suspends(client, admin_id):
    a, b, c = _two_boards(client, admin_id, "AC08")
    rule = _add(client, a, admin_id, "created_create_and_link",
                {"a_connect": c["id"], "a_board": b, "a_text": "חדש"})
    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == b).count()
    other = _board(client, admin_id, "יעד אחר AC08")
    client.patch(f"/api/boards/{a}",
                 json={"actor_id": admin_id,
                       "columns": [dict(x, connect={**x["connect"], "board_ids": [other]})
                                   if x["id"] == c["id"] else x
                                   for x in client.get(f"/api/boards/{a}").json()["columns"]]})
    _item(client, a, admin_id, "אחרי")
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.board_id == b).count() == made
    assert _status_of(rule["id"]) == "paused_error"


def test_AC_09_the_same_event_twice_is_one_business_run(client, admin_id):
    bid = _board(client, admin_id, "AC09")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        ev = cityos_main._event("status_changes_to", "item", status="done")
        cityos_main._run_automations(db, t, ev, admin_id)
        cityos_main._run_automations(db, t, ev, admin_id)
        db.commit()
    assert len([r for r in _runs(client, bid, admin_id) if r["outcome"] == "ran"]) == 1


def test_AC_10_two_rules_in_a_loop_are_stopped_and_logged(client, admin_id, member_id):
    bid = _board(client, admin_id, "AC10")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    _add(client, bid, admin_id, "status_assign_person",
         {"t_status": "done", "a_person": admin_id})
    a2 = _add(client, bid, admin_id, "assigned_set_status", {"a_status": "in_progress"})
    _add(client, bid, admin_id, "status_assign_person",
         {"t_status": "in_progress", "a_person": member_id})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    mine = [r for r in _runs(client, bid, admin_id) if r["automation_id"] == a2["id"]]
    assert len([r for r in mine if r["outcome"] == "ran"]) == 1
    assert [r for r in mine if "בשרשרת" in (r["reason"] or "")], mine


# ── AC-11 .. AC-20 ─────────────────────────────────────────────────────────

def test_AC_11_a_temporary_failure_is_retried_by_the_policy(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "AC11")
    _add(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "_apply_priority_key",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("locked")))
    _item(client, bid, admin_id)
    monkeypatch.undo()
    with Session(cityos_main.engine) as db:
        q = [r for r in db.query(AutomationQueue).filter(
            AutomationQueue.board_id == bid, AutomationQueue.done_at == None).all()  # noqa: E711
            if (r.event or {}).get("type") == "retry"]
    assert q, "a temporary failure was not queued for another go"
    assert cityos_main.AUTOMATION_RETRY_DELAYS == (1, 5, 15)
    assert cityos_main.AUTOMATION_MAX_AUTO_RETRIES == 3


def test_AC_12_a_permanent_failure_is_not_retried_and_says_why(client, admin_id):
    a, b, c = _two_boards(client, admin_id, "AC12")
    _add(client, a, admin_id, "link_added_copy_to_linked",
         {"a_fields": ["priority"], "a_connect": c["id"], "a_on_missing": "fail"})
    tid = _item(client, a, admin_id, "מקור", priority="critical")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        cityos_main._run_automations(
            db, t, cityos_main._event("link_added", "item", col=c["id"], item_ids=[]),
            admin_id)
        db.commit()
    r = _runs(client, a, admin_id)[0]
    assert r["status"] == "failed_permanent" and r["reason"], r
    with Session(cityos_main.engine) as db:
        assert not [x for x in db.query(AutomationQueue).filter(
            AutomationQueue.board_id == a, AutomationQueue.done_at == None).all()  # noqa: E711
            if (x.event or {}).get("type") == "retry"]


def test_AC_13_a_date_rule_fires_in_the_boards_timezone(client, admin_id):
    bid = _board(client, admin_id, "AC13")
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id,
                                             "timezone": "Asia/Jerusalem"})
    a = _add(client, bid, admin_id, "due_set_status", {"a_status": "done"})
    # a date rule reaches only items whose moment falls AFTER it was switched
    # on — see AC-01 — so the rule is aged and the date is in the past
    with Session(cityos_main.engine) as db:
        db.query(Automation).filter(Automation.id == a["id"]).update(
            {Automation.activated_at: cityos_main._now_naive() - timedelta(days=60)})
        db.commit()
    when = cityos_main._now_naive() - timedelta(days=2)
    tid = _item(client, bid, admin_id, due_date=when.isoformat())
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._task_status_key(t) == "done", "the date rule did not fire"


def test_AC_14_a_subitem_run_identifies_both_items(client, admin_id):
    bid = _board(client, admin_id, "AC14")
    _add(client, bid, admin_id, "subitem_done_set_priority", {"a_priority": "critical"})
    parent = _item(client, bid, admin_id, "אב")
    sub = _item(client, bid, admin_id, "תת", parent_id=parent)
    client.patch(f"/api/tasks/{sub}", json={"status": "done", "user_id": admin_id})
    r = [x for x in _runs(client, bid, admin_id) if x["status"] == "succeeded"][0]
    assert r["task_id"] == parent and r["subitem_id"] == sub, r


def test_AC_15_the_items_log_shows_the_rules_name(client, admin_id):
    bid = _board(client, admin_id, "AC15")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"}, name="סגירת קריאה")
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    rows = client.get(f"/api/tasks/{tid}/activity", headers=AS(admin_id)).json()["activity"]
    mine = [r for r in rows if r.get("origin") == "automation"]
    assert mine and "סגירת קריאה" in (mine[0]["user_name"] or ""), rows


def test_AC_16_a_reader_without_rights_sees_no_protected_detail(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "AC16")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id, "חסוי")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        t.permissions = {**(t.permissions or {}), str(guinea_id): "none"}
        db.commit()
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    theirs = _runs(client, bid, guinea_id)
    assert theirs and theirs[0]["redacted"] is True, theirs
    assert "חסוי" not in str(theirs), theirs
    assert not (theirs[0]["result"] or {}).get("steps")


def test_AC_17_the_rule_runs_on_the_server_with_no_browser(client, admin_id):
    """The whole engine is server side: the API call that changed the item is
    what fired it, and nothing in the flow touches a client."""
    bid = _board(client, admin_id, "AC17")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:        # no HTTP, no browser, no session
        t = db.query(Task).filter(Task.id == tid).first()
        cityos_main._run_automations(
            db, t, cityos_main._event("status_changes_to", "item", status="done"), None)
        db.commit()
    assert _prio(tid) == "critical"


def test_AC_18_a_successful_result_is_pushed_without_a_refresh(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "AC18")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    seen = []
    real = cityos_main.bus.publish
    monkeypatch.setattr(cityos_main.bus, "publish",
                        lambda kind, **kw: (seen.append(kind), real(kind, **kw))[1])
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    monkeypatch.undo()
    assert "task.changed" in seen, seen
    with Session(cityos_main.engine) as db:
        assert db.query(EventOutbox).filter(EventOutbox.task_id == tid).count() >= 1


def test_AC_19_the_management_page_lists_rules_with_status_and_owner(client, admin_id):
    bid = _board(client, admin_id, "AC19")
    _add(client, bid, admin_id, name="כלל א")
    d = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
    assert d["automations"], d
    one = d["automations"][0]
    assert one["status"] and one["owner_name"] and one["sentence"], one
    assert "counts" in d and d["can_manage"] is True


def test_AC_20_the_creator_is_kept_and_owns_it_by_default(client, admin_id):
    bid = _board(client, admin_id, "AC20")
    a = _add(client, bid, admin_id)
    assert a["created_by"] == admin_id and a["owner_id"] == admin_id
    assert a["owner_is_creator"] is True


# ── AC-21 .. AC-30 ─────────────────────────────────────────────────────────

def test_AC_21_a_handover_moves_the_owner_keeps_the_creator_and_is_logged(client, admin_id,
                                                                          guinea_id):
    bid = _board(client, admin_id, "AC21")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    a = _add(client, bid, admin_id)
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                     json={"owner_id": guinea_id})
    assert r.status_code == 200, r.text
    assert r.json()["owner_id"] == guinea_id and r.json()["created_by"] == admin_id
    with Session(cityos_main.engine) as db:
        rows = db.query(AuditLog).filter(AuditLog.entity_type == "automation",
                                         AuditLog.entity_id == a["id"]).all()
    assert [x for x in rows if x.action in ("owner", "transfer_owner")], \
        [(x.action, x.field_name) for x in rows]


def test_AC_22_a_blocked_owner_shows_an_indicator_and_tells_the_managers(client, admin_id,
                                                                         guinea_id):
    bid = _board(client, admin_id, "AC22")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    a = _add(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"owner_id": guinea_id})
    with Session(cityos_main.engine) as db:
        from models import User
        u = db.query(User).filter(User.id == guinea_id).first()
        was, u.is_active = u.is_active, False
        db.commit()
    try:
        row = next(x for x in client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                                         ).json()["automations"] if x["id"] == a["id"])
        assert row["needs_owner"] is True, row
        assert row["status"] == "active", "the indicator changed the status"
        with Session(cityos_main.engine) as db:
            assert db.query(Notification).filter(
                Notification.user_id == admin_id,
                Notification.type == "automation").count() >= 1
    finally:
        with Session(cityos_main.engine) as db:
            from models import User
            u = db.query(User).filter(User.id == guinea_id).first()
            u.is_active = was
            db.commit()


def test_AC_23_a_rule_with_no_owner_goes_on_running(client, admin_id):
    bid = _board(client, admin_id, "AC23")
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "critical"})
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        row.owner_id, row.created_by = None, None
        db.commit()
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert _prio(tid) == "critical", "an ownerless rule stopped working"


def test_AC_24_a_dry_run_changes_nothing_and_notifies_nobody(client, admin_id):
    bid = _board(client, admin_id, "AC24")
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        n = db.query(Notification).count()
    d = client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}",
                    json={"task_id": tid}).json()
    assert d["changed_nothing"] is True and d["notified_nobody"] is True
    assert d["verdict"] and d["summary"], d
    assert _prio(tid) != "critical"
    with Session(cityos_main.engine) as db:
        assert db.query(Notification).count() == n


def test_AC_25_a_manual_run_previews_asks_and_records_its_source(client, admin_id):
    bid = _board(client, admin_id, "AC25")
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    # the preview a confirmation is shown in front of
    d = client.get(f"/api/automations/{a['id']}/impact?user_id={admin_id}")
    assert d.status_code == 200 and d.json()["sentence"], d.text
    r = client.post(f"/api/automations/{a['id']}/run?user_id={admin_id}",
                    json={"task_id": tid})
    assert r.status_code == 200, r.text
    assert r.json()["run"]["source"] == "manual", r.json()["run"]


def test_AC_26_an_api_change_fires_and_hands_back_an_event_id(client, admin_id):
    bid = _board(client, admin_id, "AC26")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    r = client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id,
                                                "source": "api"})
    assert r.status_code == 200, r.text
    ids = r.json().get("event_ids") or []
    assert ids, r.json()
    # the call raises more than one event; the run log can be asked for any
    assert any(_runs(client, bid, admin_id, event_id=i) for i in ids), ids


def test_AC_27_a_restore_from_backup_fires_nothing(client, admin_id):
    bid = _board(client, admin_id, "AC27")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    r = client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id,
                                                "source": "migration"})
    assert r.status_code == 200, r.text
    assert _prio(tid) != "critical", "restored data set the rules off"
    assert _runs(client, bid, admin_id) == []


def test_AC_28_a_bulk_edit_is_one_event_per_item_and_one_batch(client, admin_id):
    bid = _board(client, admin_id, "AC28")
    gid = client.get(f"/api/boards/{bid}").json()["groups"][-1]["id"]
    _add(client, bid, admin_id, "moved_group_set_status",
         {"t_group": gid, "a_status": "done"})
    ids = [_item(client, bid, admin_id, f"פריט {i}") for i in range(3)]
    r = client.post(f"/api/boards/{bid}/items/move",
                    json={"actor_id": admin_id, "group_id": gid, "ids": ids})
    assert r.status_code == 200, r.text
    runs = [x for x in _runs(client, bid, admin_id) if x["trigger"] == "moved_to_group"]
    assert len(runs) == 3
    assert len({x["batch_id"] for x in runs}) == 1
    assert len({x["event_id"] for x in runs}) == 3


def test_AC_29_two_rules_on_one_field_run_in_order_and_the_last_wins(client, admin_id):
    bid = _board(client, admin_id, "AC29")
    a1 = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "low"})
    a2 = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "critical"})
    client.post(f"/api/boards/{bid}/automations/order?user_id={admin_id}",
                json={"ids": [a1["id"], a2["id"]]})
    tid = _item(client, bid, admin_id)
    assert _prio(tid) == "critical", "the later rule did not decide"
    order = [r["automation_id"] for r in sorted(_runs(client, bid, admin_id),
                                                key=lambda x: x["id"])]
    assert order == [a1["id"], a2["id"]], order


def test_AC_30_a_delayed_action_rereads_everything_when_it_comes_back(client, admin_id):
    bid = _board(client, admin_id, "AC30")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "wait", "values": {"days": 60}},
                      {"key": "post_update", "values": {"text": "אחרי"}}]})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        row = db.query(AutomationQueue).filter(AutomationQueue.task_id == tid).first()
        assert row is not None and row.version and row.resume_at
        back = datetime.now(timezone.utc) - timedelta(minutes=1)
        row.event = {**row.event, "after": back.isoformat()}
        row.resume_at = back.replace(tzinfo=None)
        db.commit()
    client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}")
    with Session(cityos_main.engine) as db:
        assert db.query(Comment).filter(Comment.task_id == tid).count() == 1


# ── AC-31 .. AC-40 ─────────────────────────────────────────────────────────

def _waiting(client, bid, admin_id, **cfg):
    base = {"a_priority": "high",
            "actions": [{"key": "wait", "values": {"days": 60}},
                        {"key": "post_update", "values": {"text": "אחרי"}}]}
    base.update(cfg)
    return _add(client, bid, admin_id, "created_set_priority", base)


def _due_now(bid):
    with Session(cityos_main.engine) as db:
        back = datetime.now(timezone.utc) - timedelta(minutes=1)
        for r in db.query(AutomationQueue).filter(
                AutomationQueue.board_id == bid,
                AutomationQueue.done_at == None).all():               # noqa: E711
            r.event = {**(r.event or {}), "after": back.isoformat()}
            r.resume_at = back.replace(tzinfo=None)
        db.commit()


def test_AC_31_a_condition_that_changed_under_the_wait_skips(client, admin_id):
    bid = _board(client, admin_id, "AC31")
    _waiting(client, bid, admin_id,
             conditions=[{"kind": "priority_is", "value": "high"}])
    tid = _item(client, bid, admin_id, priority="high")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        t.priority = "low"
        db.commit()
    _due_now(bid)
    client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}")
    assert any(r["status"] == "skipped_changed" for r in _runs(client, bid, admin_id)), \
        [r["status"] for r in _runs(client, bid, admin_id)]
    with Session(cityos_main.engine) as db:
        assert db.query(Comment).filter(Comment.task_id == tid).count() == 0


def test_AC_32_pausing_with_pending_runs_lets_the_user_choose(client, admin_id):
    bid = _board(client, admin_id, "AC32")
    a = _waiting(client, bid, admin_id)
    tid = _item(client, bid, admin_id)

    def pending():
        with Session(cityos_main.engine) as db:
            return [(r.state or "pending") for r in db.query(AutomationQueue)
                    .filter(AutomationQueue.task_id == tid,
                            AutomationQueue.done_at == None).all()]    # noqa: E711
    assert pending() == ["pending"]
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"status": "paused"})
    assert pending() == ["frozen"], pending()          # the default: held
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"status": "active"})
    assert pending() == ["pending"], pending()         # and released
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                     json={"status": "paused", "pending": "cancel"})
    assert r.status_code == 200, r.text
    assert pending() == [], pending()                  # or called off, if asked


def test_AC_33_a_retry_resumes_and_does_not_repeat_a_success(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "AC33")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "post_update", "values": {"text": "שני"}},
                      {"key": "set_status", "values": {"status": "in_progress"}}]})
    inner = cityos_main._run_one_action
    n = {"i": 0}

    def flaky(db, act, cfg, task, *a, **kw):
        if act == "set_status":
            n["i"] += 1
            if n["i"] == 1:
                raise RuntimeError("locked")
        return inner(db, act, cfg, task, *a, **kw)
    monkeypatch.setattr(cityos_main, "_run_one_action", flaky)
    tid = _item(client, bid, admin_id)
    _due_now(bid)
    client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}")
    monkeypatch.undo()
    with Session(cityos_main.engine) as db:
        assert db.query(Comment).filter(Comment.task_id == tid).count() == 1, \
            "the retry posted the update a second time"
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._task_status_key(t) == "in_progress"
    second = [r for r in _runs(client, bid, admin_id) if r["attempt"] == 2]
    assert second and ((second[0]["result"] or {}).get("steps") or [{}])[0]["index"] == 3


def test_AC_34_a_duplicate_is_a_new_draft_with_no_history(client, admin_id):
    bid = _board(client, admin_id, "AC34")
    a = _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    r = client.post(f"/api/automations/{a['id']}/duplicate?user_id={admin_id}", json={})
    assert r.status_code == 200, r.text
    copy = r.json()
    assert copy["id"] != a["id"] and copy["status"] == "draft"
    assert copy["run_count"] == 0 and copy["fail_count"] == 0
    assert _runs(client, bid, admin_id, automation_id=copy["id"]) == []


def test_AC_35_editing_an_active_rule_leaves_the_old_one_running(client, admin_id):
    bid = _board(client, admin_id, "AC35")
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "critical"})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"config": {"t_status": "done", "a_priority": "low"}})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert _prio(tid) == "critical", "the draft took effect before it was published"
    row = next(x for x in client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                                     ).json()["automations"] if x["id"] == a["id"])
    assert row["draft_version"], row
    client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}", json={})
    t2 = _item(client, bid, admin_id, "שני")
    client.patch(f"/api/tasks/{t2}", json={"status": "done", "user_id": admin_id})
    assert _prio(t2) == "low", "the published version did not take effect"


def test_AC_36_restoring_a_version_makes_a_draft_that_must_be_checked(client, admin_id):
    bid = _board(client, admin_id, "AC36")
    a = _add(client, bid, admin_id, name="שם ראשון")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"name": "שם שני"})
    r = client.post(f"/api/automations/{a['id']}/restore/1?user_id={admin_id}", json={})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["draft_version"], "a restore applied itself instead of waiting"
    assert got["name"] == "שם שני", "the live rule changed under the restore"
    d = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"automation_id": a["id"]})
    assert d.status_code == 200 and "valid" in d.json()


def test_AC_37_a_dependency_deletion_is_previewed_then_suspends(client, admin_id):
    bid = _board(client, admin_id, "AC37")
    col = _col(client, bid, admin_id, type="text", title="אזור")
    rule = _add(client, bid, admin_id, "column_changed_notify_assignees",
                {"t_column": col["id"]})
    d = client.get(f"/api/boards/{bid}/automations/dependents"
                   f"?kind=column&ref={col['id']}&user_id={admin_id}")
    assert d.status_code == 200, d.text
    deps = d.json()
    assert [x["id"] for x in deps["dependents"]] == [rule["id"]]
    assert deps["dependents"][0]["impact"] and deps["dependents"][0]["owner_name"]
    assert deps["note"], "the confirmation has nothing to say about what follows"
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id,
                       "columns": [c for c in client.get(f"/api/boards/{bid}").json()["columns"]
                                   if c["id"] != col["id"]]})
    assert _status_of(rule["id"]) == "paused_error"


def test_AC_38_a_board_that_comes_back_does_not_resume_by_itself(client, admin_id):
    bid = _board(client, admin_id, "AC38")
    rule = _add(client, bid, admin_id)
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    assert _status_of(rule["id"]) in ("paused", "paused_error")
    r = client.post(f"/api/trash/boards/{bid}/restore?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert _status_of(rule["id"]) in ("paused", "paused_error"), \
        "the restore switched the rules back on by itself"


def test_AC_39_the_organisation_page_shows_rules_failures_owners_and_quota(client, admin_id):
    d = client.get(f"/api/admin/automations?user_id={admin_id}")
    assert d.status_code == 200, d.text
    got = d.json()
    for key in ("automations", "quota"):
        assert key in got, sorted(got)
    one = (got["automations"] or [{}])[0]
    for key in ("owner_name", "status", "fail_count", "board_name"):
        assert key in one, sorted(one)
    assert got["quota"]["limit"] and "used" in got["quota"]


def test_AC_40_an_untouched_failure_is_chased_on_the_clock(client, admin_id, member_id):
    bid = _board(client, admin_id, "AC40")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "admin"})
    _add(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        before = db.query(Notification).filter(
            Notification.user_id == member_id,
            Notification.type == "automation").count()
    import main as m
    orig = m._apply_priority_key
    m._apply_priority_key = lambda *a, **k: (_ for _ in ()).throw(
        m._Refused("ערך לא חוקי"))
    try:
        _item(client, bid, admin_id)
    finally:
        m._apply_priority_key = orig
    inc = client.get(f"/api/boards/{bid}/automations/incidents?user_id={admin_id}"
                     ).json()["incidents"]
    assert inc and inc[0]["status"] == "open", inc
    with Session(cityos_main.engine) as db:
        for row in db.query(AutomationIncident).filter(
                AutomationIncident.board_id == bid).all():
            row.opened_at = cityos_main._now_naive() - timedelta(days=5)
        db.commit()
    client.get(f"/api/boards/{bid}/automations/incidents?user_id={admin_id}")
    inc = client.get(f"/api/boards/{bid}/automations/incidents?user_id={admin_id}"
                     ).json()["incidents"]
    assert inc[0]["escalated"] in ("board", "system"), inc[0]
    with Session(cityos_main.engine) as db:
        assert db.query(Notification).filter(
            Notification.user_id == member_id,
            Notification.type == "automation").count() > before


# ── AC-41 .. AC-52 ─────────────────────────────────────────────────────────

def _quota(client, admin_id, **q):
    r = client.patch(f"/api/organization/settings?user_id={admin_id}", json={"quota": q})
    assert r.status_code == 200, r.text
    return r.json()["quota"]


def test_AC_41_eighty_percent_warns_and_loses_nothing(client, admin_id):
    bid = _board(client, admin_id, "AC41")
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        used = cityos_main._automation_quota(db)["used"]
    _quota(client, admin_id, monthly_runs=max(2, int(used / 0.85)), enforce=False)
    try:
        h = client.get(f"/api/admin/automations/health?user_id={admin_id}").json()
        assert h["quota"]["warning"] is True and h["quota"]["blocked"] is False
        tid = _item(client, bid, admin_id, "אחרי האזהרה")
        assert _prio(tid) == "high", "the warning stopped the work"
    finally:
        _quota(client, admin_id, monthly_runs=None, enforce=False)


def test_AC_42_an_exhausted_event_lands_in_the_dlq_and_can_be_replayed(client, admin_id):
    bid = _board(client, admin_id, "AC42")
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        for r in db.query(EventOutbox).filter(EventOutbox.board_id == bid).all():
            r.sent_at, r.attempts = None, cityos_main.OUTBOX_MAX_ATTEMPTS
        db.commit()
    real = cityos_main.bus.publish
    try:
        cityos_main.bus.publish = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("bus down"))
        with Session(cityos_main.engine) as db:
            cityos_main._drain_outbox(db, bid)
            db.commit()
    finally:
        cityos_main.bus.publish = real
    h = client.get(f"/api/admin/automations/health?user_id={admin_id}").json()
    assert h["outbox"]["dead"] >= 1, h["outbox"]
    r = client.post(f"/api/admin/automations/outbox/replay?user_id={admin_id}",
                    json={"board_id": bid})
    assert r.status_code == 200, r.text
    assert r.json()["replayed"] >= 1, r.json()
    with Session(cityos_main.engine) as db:
        assert db.query(EventOutbox).filter(EventOutbox.board_id == bid,
                                            EventOutbox.dead_at != None).count() == 0  # noqa: E711


def test_AC_43_the_detailed_log_shows_source_conditions_and_actions(client, admin_id):
    bid = _board(client, admin_id, "AC43")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "conditions": [{"kind": "priority_is", "value": "low"}]})
    tid = _item(client, bid, admin_id, priority="low")
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    r = [x for x in _runs(client, bid, admin_id) if x["outcome"] == "ran"][0]
    assert r["source"] and (r["result"] or {}).get("conditions")
    assert (r["result"] or {}).get("steps")
    d = client.get(f"/api/automation-runs/{r['id']}/timeline?user_id={admin_id}")
    assert d.status_code == 200 and d.json()["timeline"]


def test_AC_44_an_export_filters_the_protected_and_is_recorded(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "AC44")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id, "חסוי")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        t.permissions = {**(t.permissions or {}), str(guinea_id): "none"}
        db.commit()
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    from models import RolePermission, User
    with Session(cityos_main.engine) as db:
        role = db.query(User.role).filter(User.id == guinea_id).scalar() or "guest"
        row = (db.query(RolePermission).filter(
            RolePermission.role == role,
            RolePermission.capability == "export_automation_log").first())
        if not row:
            row = RolePermission(role=role, capability="export_automation_log",
                                 allowed=True)
            db.add(row)
        row.allowed = True
        db.commit()
    try:
        theirs = client.get(f"/api/boards/{bid}/automations/runs/export"
                            f"?user_id={guinea_id}")
        assert theirs.status_code == 200 and "חסוי" not in theirs.text
    finally:
        with Session(cityos_main.engine) as db:
            r2 = (db.query(RolePermission).filter(
                RolePermission.role == role,
                RolePermission.capability == "export_automation_log").first())
            r2.allowed = False
            db.commit()
    with Session(cityos_main.engine) as db:
        assert db.query(AuditLog).filter(
            AuditLog.entity_type == "automation_export",
            AuditLog.entity_id == bid).count() >= 1


def test_AC_45_an_emergency_stop_needs_a_reason_and_deletes_nothing(client, admin_id):
    bid = _board(client, admin_id, "AC45")
    a = _add(client, bid, admin_id)
    assert client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                       json={"scope": "org", "reason": "קצר"}).status_code == 400
    assert client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                       json={"scope": "org",
                             "reason": "חקירת תקלה רוחבית במערכת"}).status_code == 400
    r = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "org", "reason": "חקירת תקלה רוחבית במערכת",
                          "confirm": True})
    assert r.status_code == 200, r.text
    try:
        tid = _item(client, bid, admin_id)
        assert _prio(tid) != "high", "a frozen board still ran"
        with Session(cityos_main.engine) as db:
            assert db.query(Automation).filter(Automation.id == a["id"]).first() is not None
    finally:
        fid = r.json()["freeze"]["id"]
        client.post(f"/api/admin/automations/release?user_id={admin_id}",
                    json={"freeze_id": fid, "reason": "הסתיים"})


def test_AC_46_calling_off_one_pending_run_leaves_the_others(client, admin_id):
    bid = _board(client, admin_id, "AC46")
    _waiting(client, bid, admin_id)
    a, b = _item(client, bid, admin_id, "א"), _item(client, bid, admin_id, "ב")
    rows = [r for r in _runs(client, bid, admin_id) if r["status"] == "queued"]
    assert len(rows) == 2, [r["status"] for r in _runs(client, bid, admin_id)]
    mine = next(r for r in rows if r["task_id"] == a)
    r = client.post(f"/api/automation-queue/{mine['queue_id']}/cancel?user_id={admin_id}")
    assert r.status_code == 200, r.text
    left = [x for x in _runs(client, bid, admin_id) if x["status"] == "queued"]
    assert [x["task_id"] for x in left] == [b], left


def test_AC_47_a_template_that_does_not_fit_cannot_be_switched_on(client, admin_id):
    bid = _board(client, admin_id, "AC47")
    d = client.get(f"/api/boards/{bid}/automations/templates?user_id={admin_id}").json()
    bad = [t for t in d["templates"] if not t.get("available")]
    assert bad, "every template fits this board — nothing to check"
    one = bad[0]
    assert one["missing"], one          # and it says WHICH pieces are absent
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": one["id"],
                          "config": {}, "status": "active"})
    assert r.status_code == 400, r.text


def test_AC_48_the_status_creates_an_item_in_the_chosen_group_and_board(client, admin_id):
    a, b, c = _two_boards(client, admin_id, "AC48")
    grp = client.post("/api/groups", json={"board_id": b, "name": "נכנסים",
                                           "actor_id": admin_id}).json()["id"]
    _add(client, a, admin_id, "status_create_in_group_and_link",
         {"t_status": "done", "a_connect": c["id"], "a_board": b,
          "a_target_group": grp, "a_text": "ביצוע", "a_fields": ["priority"]})
    tid = _item(client, a, admin_id, "בקשה", priority="critical")
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == b, Task.title == "ביצוע").all()
    assert len(made) == 1 and made[0].group_id == grp, made


def test_AC_49_the_name_and_the_mapped_fields_travel(client, admin_id):
    a, b, c = _two_boards(client, admin_id, "AC49")
    grp = client.post("/api/groups", json={"board_id": b, "name": "נכנסים",
                                           "actor_id": admin_id}).json()["id"]
    src = _col(client, a, admin_id, id="col_s", type="text", title="אזור")
    dst = _col(client, b, admin_id, id="col_d", type="text", title="אזור יעד")
    _add(client, a, admin_id, "created_set_status",
         {"a_status": "in_progress",
          "actions": [{"key": "create_mapped_and_link",
                       "values": {"connect": c["id"], "board": b, "target_group": grp,
                                  "text": "ביצוע: {{item.name}}",
                                  "map": [{"from": src["id"], "to": dst["id"]}]}}]})
    _item(client, a, admin_id, "מדרכה", custom_fields={"col_s": "צפון"})
    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == b).all()
    assert len(made) == 1, [m.title for m in made]
    assert "מדרכה" in made[0].title, made[0].title
    assert (made[0].custom_fields or {}).get("col_d") == "צפון", made[0].custom_fields


def test_AC_50_a_repeat_event_or_retry_makes_no_second_item(client, admin_id):
    a, b, c = _two_boards(client, admin_id, "AC50")
    grp = client.post("/api/groups", json={"board_id": b, "name": "נכנסים",
                                           "actor_id": admin_id}).json()["id"]
    _add(client, a, admin_id, "status_create_in_group_and_link",
         {"t_status": "done", "a_connect": c["id"], "a_board": b,
          "a_target_group": grp, "a_text": "ביצוע", "a_fields": ["priority"]})
    tid = _item(client, a, admin_id, "בקשה")
    for st in ("done", "todo", "done"):
        client.patch(f"/api/tasks/{tid}", json={"status": st, "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.board_id == b).count() == 1
    sk = [r for r in _runs(client, a, admin_id)
          if "פריט יעד כבר קיים" in (r["reason"] or "")]
    assert sk, [r["reason"] for r in _runs(client, a, admin_id)]


def test_AC_51_the_two_items_are_linked_and_the_log_names_the_new_one(client, admin_id):
    a, b, c = _two_boards(client, admin_id, "AC51")
    grp = client.post("/api/groups", json={"board_id": b, "name": "נכנסים",
                                           "actor_id": admin_id}).json()["id"]
    _add(client, a, admin_id, "status_create_in_group_and_link",
         {"t_status": "done", "a_connect": c["id"], "a_board": b,
          "a_target_group": grp, "a_text": "ביצוע", "a_fields": ["priority"]})
    tid = _item(client, a, admin_id, "בקשה")
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == b).first()
        assert made is not None
        assert made.id in cityos_main._linked_ids(db, tid, c["id"])
        mirror = c["connect"]["mirror"][str(b)]
        assert tid in cityos_main._linked_ids(db, made.id, mirror)
    run = [r for r in _runs(client, a, admin_id) if r["outcome"] == "ran"][0]
    created = (run["result"] or {}).get("created") or []
    assert created and created[0]["task_id"] == made.id, run["result"]


def test_AC_52_a_broken_mapping_creates_nothing_and_says_why(client, admin_id):
    a, b, c = _two_boards(client, admin_id, "AC52")
    grp = client.post("/api/groups", json={"board_id": b, "name": "נכנסים",
                                           "actor_id": admin_id}).json()["id"]
    src = _col(client, a, admin_id, id="col_sd", type="dropdown", title="אזור",
               options=[{"label": "צפון"}])
    dst = _col(client, b, admin_id, id="col_dd", type="dropdown", title="צד",
               options=[{"label": "מזרח"}])
    _add(client, a, admin_id, "created_set_status",
         {"a_status": "in_progress",
          "actions": [{"key": "create_mapped_and_link",
                       "values": {"connect": c["id"], "board": b, "target_group": grp,
                                  "text": "ממופה",
                                  "map": [{"from": src["id"], "to": dst["id"]}]}}]})
    _item(client, a, admin_id, "מקור", custom_fields={"col_sd": "צפון"})
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.board_id == b).count() == 0, \
            "a partial item was created"
    r = _runs(client, a, admin_id)[0]
    assert r["outcome"] == "failed" and r["reason"], r
    assert "היעד" in r["reason"] or "מיפוי" in r["reason"], r["reason"]


# ── נוסחי ההודעות שהטבלה מציעה ─────────────────────────────────────────────

def test_the_five_standard_messages_are_the_ones_the_table_proposes(client):
    """Five states, five sentences, written once. A message assembled at each
    call site drifts: three screens end up saying three different things
    about the same state, and the one a person acts on is whichever they
    happened to open."""
    m = cityos_main.AUTOMATION_SAY
    assert m["activated"] == ("האוטומציה נשמרה והופעלה. "
                              "היא תחול על אירועים חדשים מעכשיו")
    assert m["dependency"] == ("האוטומציה הושהתה משום שרכיב נדרש נמחק. "
                               "יש לבחור חלופה ולהפעיל מחדש")
    assert m["permission"] == ("לא ניתן להפעיל את האוטומציה. "
                               "חסרה הרשאת עריכה ביעד")
    assert m["loop"] == ("שרשרת הפעולות נעצרה כדי למנוע הפעלה מעגלית. "
                         "פרטים זמינים בלוג")
    assert m["condition"] == ("האוטומציה נבדקה אך הפעולות לא בוצעו "
                              "משום שהתנאים לא התקיימו")


def test_the_messages_reach_the_places_they_describe(client, admin_id):
    bid = _board(client, admin_id, "AC-נוסחים")
    col = _col(client, bid, admin_id, type="text", title="אזור")
    rule = _add(client, bid, admin_id, "column_changed_notify_assignees",
                {"t_column": col["id"]})
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id,
                       "columns": [c for c in client.get(f"/api/boards/{bid}").json()["columns"]
                                   if c["id"] != col["id"]]})
    row = next(x for x in client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                                     ).json()["automations"] if x["id"] == rule["id"])
    assert row["say"] == cityos_main.AUTOMATION_SAY["dependency"], row.get("say")

    bid2 = _board(client, admin_id, "AC-נוסח תנאי")
    _add(client, bid2, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "conditions": [{"kind": "has_assignee", "value": True}]})
    tid = _item(client, bid2, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    r = _runs(client, bid2, admin_id)[0]
    assert r["say"] == cityos_main.AUTOMATION_SAY["condition"], r.get("say")
