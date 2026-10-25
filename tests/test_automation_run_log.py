"""Group — לוג הפעלות: what a run was, in enough detail to answer with.

Three coarse outcomes answered "did it work". They do not answer the questions
somebody actually arrives with: did it skip because the condition was false or
because a value it needed was not there; is this failure worth trying again or
is it the same every time; how long did it sit between the event arriving and
the rule starting; which of the four conditions was the one that said no; what
did the second action actually write, and where.

So the log keeps the fine status out of eleven, the three moments, the attempt
number, the error code, every condition's verdict and every action's input,
target and output — and the screen can search it, read it as a timeline, copy
an id for support and call off a run that has not gone yet.

What it still must not do is say any of that to somebody who may not see the
item. A log is a log of real data.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AutomationQueue, AutomationRun, Task

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title="פריט", **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **kw}).json()["id"]


def _add(client, bid, admin_id, recipe_id, config, **extra):
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": recipe_id,
                          "config": config, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _log(client, bid, admin_id, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    r = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}{qs}")
    assert r.status_code == 200, r.text
    return r.json()


def _runs(client, bid, admin_id, **q):
    return _log(client, bid, admin_id, **q)["runs"]


def _shut_out(tid, uid):
    """Take one person's access to one item away. A per-item override beats the
    board role, which is the only way a board ADMIN can be kept out of an item
    — and a board admin is who the log is written for."""
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        t.permissions = {**(t.permissions or {}), str(uid): "none"}
        db.commit()


def _col(client, bid, admin_id, **spec):
    cols = client.get(f"/api/boards/{bid}").json()["columns"]
    col = {"id": spec.pop("id", "col_" + spec["type"][:4] + str(len(cols))), **spec}
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols + [col]})
    return col


# ── מה כל שורה שומרת ───────────────────────────────────────────────────────

def test_a_run_keeps_the_whole_schema(client, admin_id):
    bid = _board(client, admin_id, "לוח סכמה")
    rule = _add(client, bid, admin_id, "status_set_priority",
                {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    r = _runs(client, bid, admin_id)[0]
    for key in ("id", "automation_id", "version", "queued_at", "started_at",
                "finished_at", "task_id", "source", "actor_id", "status",
                "attempt", "error_code", "chain_id", "event_id", "result"):
        assert key in r, f"the log has no {key}"
    assert r["automation_id"] == rule["id"] and r["version"]
    assert r["task_id"] == tid
    assert r["queued_at"] and r["started_at"] and r["finished_at"], r


def test_the_three_moments_are_in_order(client, admin_id):
    """«זמני קליטת האירוע, תחילת הביצוע וסיומו» — three, because the gap
    between the first two is the queue and between the last two is the work."""
    bid = _board(client, admin_id, "לוח זמנים")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    r = _runs(client, bid, admin_id)[0]
    q, s, f = r["queued_at"], r["started_at"], r["finished_at"]
    assert q <= s <= f, (q, s, f)


def test_the_old_and_new_value_are_kept(client, admin_id):
    bid = _board(client, admin_id, "לוח ערכים")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    r = _runs(client, bid, admin_id)[0]
    assert (r["result"] or {}).get("old") == "todo", r["result"]
    assert (r["result"] or {}).get("new") == "done", r["result"]


def test_every_condition_gets_a_verdict(client, admin_id):
    """«תוצאת כל תנאי» — each one, not just the one that decided. Over OR the
    one that passed is the interesting one; over AND it is the one that did not."""
    bid = _board(client, admin_id, "לוח תנאים")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "conditions": [{"kind": "priority_is", "value": "low"},
                         {"kind": "has_assignee", "value": True}]})
    tid = _item(client, bid, admin_id, priority="low")
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    r = _runs(client, bid, admin_id)[0]
    conds = (r["result"] or {}).get("conditions") or []
    assert len(conds) == 2, conds
    assert {c["kind"] for c in conds} == {"priority_is", "has_assignee"}
    assert conds[0]["held"] is True and conds[1]["held"] is False, conds
    assert all(c.get("text") for c in conds), "a verdict with no words is not a verdict"


def test_every_action_records_what_it_did(client, admin_id):
    """«קלט, יעד ופלט של כל פעולה»."""
    bid = _board(client, admin_id, "לוח פעולות")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "actions": [{"key": "post_update", "values": {"text": "נסגר"}}]})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    r = _runs(client, bid, admin_id)[0]
    steps = (r["result"] or {}).get("steps") or []
    assert len(steps) == 2, steps
    assert [s["key"] for s in steps] == ["set_priority", "post_update"]
    assert all("input" in s and "target" in s and "output" in s for s in steps), steps
    assert steps[0]["target"]["task_id"] == tid, steps[0]


def test_a_subitem_run_says_which_subitem(client, admin_id):
    bid = _board(client, admin_id, "לוח תת-פריט לוג")
    _add(client, bid, admin_id, "subitem_done_set_priority", {"a_priority": "critical"})
    parent = _item(client, bid, admin_id, "אב")
    sub = _item(client, bid, admin_id, "תת", parent_id=parent)
    client.patch(f"/api/tasks/{sub}", json={"status": "done", "user_id": admin_id})
    r = [x for x in _runs(client, bid, admin_id) if x["status"] == "succeeded"][0]
    assert r["subitem_id"] == sub, r
    assert r["task_id"] == parent


# ── אחד־עשר הסטטוסים ───────────────────────────────────────────────────────

def test_all_eleven_statuses_are_declared(client, admin_id):
    want = {"queued", "running", "succeeded", "partial", "skipped_condition",
            "skipped_missing", "skipped_changed", "failed_temporary",
            "failed_permanent", "cancelled", "loop_stopped"}
    assert set(cityos_main.RUN_STATUSES) == want, set(cityos_main.RUN_STATUSES) ^ want
    assert all(cityos_main.RUN_STATUS_HE.get(s) for s in want), cityos_main.RUN_STATUS_HE


def test_a_plain_success(client, admin_id):
    bid = _board(client, admin_id, "לוח הצלחה")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert _runs(client, bid, admin_id)[0]["status"] == "succeeded"


def test_a_condition_that_did_not_hold(client, admin_id):
    bid = _board(client, admin_id, "לוח תנאי")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "conditions": [{"kind": "has_assignee", "value": True}]})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert _runs(client, bid, admin_id)[0]["status"] == "skipped_condition"


def test_a_datum_the_rule_needed_and_did_not_find(client, admin_id):
    """«דולגה - נתון חסר לפי הגדרה» — the author said what a missing link
    means, and it was "skip". A different silence from a false condition."""
    a, b = _board(client, admin_id, "מקור חסר"), _board(client, admin_id, "יעד חסר")
    cols = client.get(f"/api/boards/{a}").json()["columns"] + [
        {"type": "connect", "title": "קישור",
         "connect": {"board_ids": [b], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in client.get(f"/api/boards/{a}").json()["columns"]
             if x["type"] == "connect")
    _add(client, a, admin_id, "link_added_copy_to_linked",
         {"a_fields": ["priority"], "a_connect": c["id"]})
    tid = _item(client, a, admin_id, "מקור", priority="critical")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        cityos_main._run_automations(
            db, t, cityos_main._event("link_added", "item", col=c["id"], item_ids=[]),
            admin_id)
        db.commit()
    assert _runs(client, a, admin_id)[0]["status"] == "skipped_missing"


def test_a_partial_success(client, admin_id):
    """«הצליחה חלקית» — one action worked and one had nothing to do, which is
    neither a success nor a skip and used to be filed as a success."""
    bid = _board(client, admin_id, "לוח חלקי")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "actions": [{"key": "set_status", "values": {"status": "done"}}]})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    r = _runs(client, bid, admin_id)[0]
    assert r["status"] == "partial", r


def test_a_permanent_failure(client, admin_id):
    """A refusal is a decision the engine made and will make again."""
    a, b = _board(client, admin_id, "מקור קבוע"), _board(client, admin_id, "יעד קבוע")
    cols = client.get(f"/api/boards/{a}").json()["columns"] + [
        {"type": "connect", "title": "קישור",
         "connect": {"board_ids": [b], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in client.get(f"/api/boards/{a}").json()["columns"]
             if x["type"] == "connect")
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
    assert r["status"] == "failed_permanent", r
    assert r["error_code"], "a failure with no code cannot be grouped or searched"


def test_a_temporary_failure(client, admin_id, monkeypatch):
    """A crash is not a decision: it may well work next time, and the log has
    to say which of the two this was or «נסה שוב» is a coin toss."""
    bid = _board(client, admin_id, "לוח זמני")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    real = cityos_main._apply_priority_key

    def boom(*args, **kw):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(cityos_main, "_apply_priority_key", boom)
    _item(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "_apply_priority_key", real)
    r = _runs(client, bid, admin_id)[0]
    assert r["status"] == "failed_temporary", r
    assert r["error_code"] == "RuntimeError", r


def test_a_chain_cut_is_its_own_status(client, admin_id):
    bid = _board(client, admin_id, "לוח לולאה לוג")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        cityos_main._run_automations(
            db, t, cityos_main._event("status_changes_to", "item", status="done",
                                      chain_runs=cityos_main.AUTOMATION_CHAIN_MAX_RUNS),
            admin_id)
        db.commit()
    assert _runs(client, bid, admin_id)[0]["status"] == "loop_stopped"


def test_conditions_that_changed_under_a_wait(client, admin_id):
    bid = _board(client, admin_id, "לוח המתנה השתנה")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "conditions": [{"kind": "priority_is", "value": "high"}],
          "actions": [{"key": "wait", "values": {"days": 60}},
                      {"key": "post_update", "values": {"text": "אחרי"}}]})
    tid = _item(client, bid, admin_id, priority="high")   # the condition holds NOW
    with Session(cityos_main.engine) as db:
        row = db.query(AutomationQueue).filter(AutomationQueue.task_id == tid).first()
        assert row is not None
        row.event = {**row.event,
                     "after": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
        row.resume_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        t = db.query(Task).filter(Task.id == tid).first()
        t.priority = "low"                      # the condition no longer holds
        db.commit()
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert any(r["status"] == "skipped_changed" for r in _runs(client, bid, admin_id)), \
        [r["status"] for r in _runs(client, bid, admin_id)]


def test_the_coarse_outcome_still_works_for_everything_built_on_it(client, admin_id):
    """Eleven statuses do not replace three outcomes — they sit under them, so
    the chips, the filters and the counts that already read `outcome` go on
    reading it and mean the same thing."""
    for st, want in (("succeeded", "ran"), ("partial", "ran"),
                     ("skipped_condition", "skipped"), ("skipped_missing", "skipped"),
                     ("skipped_changed", "skipped"), ("loop_stopped", "skipped"),
                     ("failed_temporary", "failed"), ("failed_permanent", "failed"),
                     ("cancelled", "skipped")):
        assert cityos_main.RUN_OUTCOME_OF[st] == want, st


# ── מספר ניסיונות ─────────────────────────────────────────────────────────

def test_a_retry_counts_as_a_second_attempt(client, admin_id):
    bid = _board(client, admin_id, "לוח ניסיונות")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "conditions": [{"kind": "has_assignee", "value": True}]})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    first = _runs(client, bid, admin_id)[0]
    assert first["attempt"] == 1, first
    r = client.post(f"/api/automation-runs/{first['id']}/retry?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert r.json()["run"]["attempt"] == 2, r.json()["run"]


# ── המסך: חיפוש, ציר זמן, העתקה, ביטול ───────────────────────────────────

def test_the_log_can_be_searched(client, admin_id):
    bid = _board(client, admin_id, "לוח חיפוש")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id, "צינור ראשי")
    _item(client, bid, admin_id, "מדרכה")
    found = _runs(client, bid, admin_id, q="צינור")
    assert len(found) == 1 and found[0]["task_title"] == "צינור ראשי", found


def test_the_search_reaches_the_reason_too(client, admin_id):
    bid = _board(client, admin_id, "לוח חיפוש סיבה")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "conditions": [{"kind": "has_assignee", "value": True}]})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert _runs(client, bid, admin_id, q="התנאי"), "the reason is not searchable"


def test_the_log_can_be_filtered_by_the_fine_status(client, admin_id):
    bid = _board(client, admin_id, "לוח סינון מדויק")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _add(client, bid, admin_id, "created_set_status",
         {"a_status": "done", "conditions": [{"kind": "has_assignee", "value": True}]})
    _item(client, bid, admin_id)
    got = _runs(client, bid, admin_id, status="skipped_condition")
    assert got and all(r["status"] == "skipped_condition" for r in got), got
    assert len(got) < len(_runs(client, bid, admin_id))


def test_the_counts_cover_every_status(client, admin_id):
    bid = _board(client, admin_id, "לוח מונים")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    d = _log(client, bid, admin_id)
    assert d["counts"]["succeeded"] == 1, d["counts"]
    assert d["counts"]["ran"] == 1, "the coarse counts stopped working"
    assert set(cityos_main.RUN_STATUSES) <= set(d["counts"]), d["counts"]


def test_a_waiting_run_is_in_the_log_as_queued(client, admin_id):
    """«ממתינה» is a status of the log, and «ביטול הפעלה ממתינה» is something
    the log screen does — so the run that has not gone yet has to be ON it."""
    bid = _board(client, admin_id, "לוח ממתינה")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "wait", "values": {"days": 60}},
                      {"key": "post_update", "values": {"text": "אחרי"}}]})
    tid = _item(client, bid, admin_id)
    waiting = [r for r in _runs(client, bid, admin_id) if r["status"] == "queued"]
    assert waiting, [r["status"] for r in _runs(client, bid, admin_id)]
    assert waiting[0]["task_id"] == tid
    assert waiting[0].get("queue_id"), "a queued row with no handle cannot be cancelled"


def test_a_waiting_run_can_be_called_off_from_the_log(client, admin_id):
    bid = _board(client, admin_id, "לוח ביטול")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "wait", "values": {"days": 60}},
                      {"key": "post_update", "values": {"text": "אחרי"}}]})
    tid = _item(client, bid, admin_id)
    qid = [r for r in _runs(client, bid, admin_id) if r["status"] == "queued"][0]["queue_id"]
    r = client.post(f"/api/automation-queue/{qid}/cancel?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert not [x for x in _runs(client, bid, admin_id) if x["status"] == "queued"]


def test_only_a_manager_may_call_one_off(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח ביטול הרשאה")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "wait", "values": {"days": 60}},
                      {"key": "post_update", "values": {"text": "אחרי"}}]})
    _item(client, bid, admin_id)
    qid = [r for r in _runs(client, bid, admin_id) if r["status"] == "queued"][0]["queue_id"]
    assert client.post(f"/api/automation-queue/{qid}/cancel?user_id={member_id}"
                       ).status_code == 403


def test_the_support_handles_are_on_every_row(client, admin_id):
    """«העתקת מזהה לתמיכה» — and the id that matters for support is not one
    id: the run, the event it came from, and the chain it belonged to."""
    bid = _board(client, admin_id, "לוח תמיכה")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    r = _runs(client, bid, admin_id)[0]
    assert r["ref"], "no single string to hand to support"
    for part in (str(r["id"]), r["chain_id"]):
        assert part in r["ref"], (part, r["ref"])


def test_the_timeline_reads_in_order(client, admin_id):
    """«ציר זמן מפורט» — the event arriving, each condition, each action, the
    end. Built on the server so the screen is not reassembling a story from
    four fields it hopes line up."""
    bid = _board(client, admin_id, "לוח ציר זמן")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "conditions": [{"kind": "priority_is", "value": "low"}],
          "actions": [{"key": "post_update", "values": {"text": "נסגר"}}]})
    tid = _item(client, bid, admin_id, priority="low")
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    run = _runs(client, bid, admin_id)[0]
    d = client.get(f"/api/automation-runs/{run['id']}/timeline?user_id={admin_id}")
    assert d.status_code == 200, d.text
    steps = d.json()["timeline"]
    kinds = [s["kind"] for s in steps]
    assert kinds[0] == "event" and kinds[-1] == "end", kinds
    assert "condition" in kinds and kinds.count("action") == 2, kinds
    assert all(s.get("text") for s in steps), steps


# ── מה לא נחשף ─────────────────────────────────────────────────────────────

def test_the_detail_is_hidden_from_somebody_who_may_not_see_the_item(client, admin_id, guinea_id):
    """Everything added here is read off real data — the old value, the new
    one, each condition's actual verdict, what each action wrote. All of it
    goes out with the rest when the reader may not see the item."""
    # a board ADMIN, because an editor may not read the log at all (see
    # _can_view_automations) — the point here is somebody who may read the log
    # and may NOT see this particular item
    bid = _board(client, admin_id, "לוח מוגן")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "actions": [{"key": "post_update", "values": {"text": "סודי"}}]})
    tid = _item(client, bid, admin_id, "חסוי")
    _shut_out(tid, guinea_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    mine = _runs(client, bid, admin_id)[0]
    assert (mine["result"] or {}).get("steps"), "the owner cannot see it either"
    theirs = [r for r in _runs(client, bid, guinea_id) if r["id"] == mine["id"]]
    if theirs:
        r = theirs[0]
        assert r["redacted"] is True, r
        assert not (r["result"] or {}).get("steps"), r["result"]
        assert not (r["result"] or {}).get("conditions"), r["result"]
        assert "סודי" not in str(r), r


def test_the_timeline_is_refused_to_somebody_who_may_not_see_the_item(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח ציר מוגן")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id, "חסוי")
    _shut_out(tid, guinea_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    run = _runs(client, bid, admin_id)[0]
    assert client.get(f"/api/automation-runs/{run['id']}/timeline?user_id={guinea_id}"
                      ).status_code == 403


def test_the_log_is_still_closed_to_a_stranger(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח זר")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    assert client.get(f"/api/boards/{bid}/automations/runs?user_id={guinea_id}"
                      ).status_code == 403


def test_the_export_carries_the_new_columns(client, admin_id):
    bid = _board(client, admin_id, "לוח ייצוא")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    r = client.get(f"/api/boards/{bid}/automations/runs/export?user_id={admin_id}")
    assert r.status_code == 200, r.text
    head = r.text.splitlines()[0]
    for want in ("סטטוס", "ניסיון", "שרשרת"):
        assert want in head, (want, head)
