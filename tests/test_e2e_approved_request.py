"""סעיף 16 — התרחיש מקצה לקצה: בקשה שאושרה.

One rule, end to end, over everything the earlier sections built:

    כאשר הסטטוס משתנה ל«מאושר»,
    ואם סוג הבקשה הוא «דורשת ביצוע»,
    צור תת־פריט «ביצוע: …», שייך אחראי, והוסף עדכון לשיחה.

Nothing here is new engine work. The point is the opposite — that fourteen
sections of separate pieces compose into the one flow somebody actually asked
for, and that each guarantee made along the way still holds when it is not
the only thing being tested: the conditions are read before the actions, the
actions run in the order they were written, every step is on the row, the
event goes out after the write and not before, a temporary failure resumes at
the action that failed without repeating the two that worked, and a permanent
one reaches the owner.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import (Automation, AutomationIncident, AutomationQueue,
                    AutomationRun, Comment, EventOutbox, Notification, Task)

AS = lambda uid: {"X-CityOS-User": str(uid)}
APPROVED = "x_approved"


# ── the board the scenario happens on ──────────────────────────────────────

def _scenario(client, admin_id, member_id, name):
    """A requests board: a status for "מאושר", a column for the request type,
    a rule that reacts to the first and asks about the second."""
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}
                      ).json()["id"]
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    # "מאושר" is not one of the seven built-ins — a requests board defines it
    st = client.get(f"/api/boards/{bid}").json()["statuses"]
    r = client.patch(f"/api/boards/{bid}",
                     json={"actor_id": admin_id,
                           "statuses": st + [{"key": APPROVED, "label": "מאושר",
                                              "base": "review", "color": "#22c55e"}]})
    assert r.status_code == 200, r.text
    cols = client.get(f"/api/boards/{bid}").json()["columns"]
    kind = {"id": "col_kind", "type": "dropdown", "title": "סוג הבקשה",
            "options": [{"label": "דורשת ביצוע"}, {"label": "לידיעה בלבד"}]}
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id,
                                                 "columns": cols + [kind]})
    assert r.status_code == 200, r.text
    rule = client.post(f"/api/boards/{bid}/automations",
                       json={"actor_id": admin_id,
                             "recipe_id": "status_create_subitem",
                             "name": "בקשה שאושרה — פתיחת ביצוע",
                             "owner_id": admin_id,
                             "config": {
                                 "t_status": APPROVED,
                                 "a_text": "ביצוע: {{item.name}}",
                                 "conditions": [{"kind": "column_is",
                                                 "value": {"col": "col_kind",
                                                           "type": "dropdown",
                                                           "value": "דורשת ביצוע"}}],
                                 "actions": [
                                     {"key": "assign_person", "values": {"person": member_id}},
                                     {"key": "post_update",
                                      "values": {"text": "הבקשה אושרה — נפתח ביצוע"}}]}})
    assert rule.status_code == 200, rule.text
    return bid, rule.json()


def _request(client, bid, admin_id, title, kind="דורשת ביצוע"):
    r = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                        "user_id": admin_id,
                                        "custom_fields": {"col_kind": kind}})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _approve(client, tid, admin_id):
    r = client.patch(f"/api/tasks/{tid}", json={"status": APPROVED, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}"
                      ).json()["runs"]


def _subs(parent):
    with Session(cityos_main.engine) as db:
        return db.query(Task).filter(Task.parent_id == parent).all()


def _updates(tid):
    with Session(cityos_main.engine) as db:
        return [c.content for c in db.query(Comment).filter(Comment.task_id == tid).all()]


# ── 1. הזרימה התקינה ───────────────────────────────────────────────────────

def test_approving_a_request_that_needs_doing_opens_the_work(client, admin_id, member_id):
    bid, rule = _scenario(client, admin_id, member_id, "בקשות ציבור")
    tid = _request(client, bid, admin_id, "תיקון מדרכה ברחוב הרצל")
    _approve(client, tid, admin_id)

    subs = _subs(tid)
    assert len(subs) == 1, [s.title for s in subs]
    assert "תיקון מדרכה" in subs[0].title, subs[0].title
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert member_id in [u.id for u in t.assignees], "nobody was put on it"
    assert any("הבקשה אושרה" in c for c in _updates(tid)), _updates(tid)
    assert rule["id"]


def test_a_request_that_is_only_for_information_is_left_alone(client, admin_id, member_id):
    """The condition is the half of the rule that decides whether any of this
    is the right thing to do at all."""
    bid, _ = _scenario(client, admin_id, member_id, "בקשות לידיעה")
    tid = _request(client, bid, admin_id, "עדכון תושבים", kind="לידיעה בלבד")
    _approve(client, tid, admin_id)
    assert _subs(tid) == []
    run = _runs(client, bid, admin_id)[0]
    assert run["status"] == "skipped_condition", run
    conds = (run["result"] or {}).get("conditions") or []
    assert conds and conds[0]["held"] is False, conds


def test_any_other_status_does_nothing(client, admin_id, member_id):
    bid, _ = _scenario(client, admin_id, member_id, "בקשות בסטטוס אחר")
    tid = _request(client, bid, admin_id, "בקשה")
    client.patch(f"/api/tasks/{tid}", json={"status": "review", "user_id": admin_id})
    assert _subs(tid) == []
    assert not [r for r in _runs(client, bid, admin_id) if r["outcome"] == "ran"]


# ── 2. אימות: שדות, ערכים, הרשאות והתנגשויות ──────────────────────────────

def test_the_rule_cannot_be_switched_on_half_written(client, admin_id, member_id):
    bid, _ = _scenario(client, admin_id, member_id, "בקשות חצי")
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": "status_create_subitem",
                          "config": {"t_status": APPROVED}})
    assert r.status_code == 400, r.text
    assert "חסר" in r.json()["detail"], r.json()


def test_a_status_the_board_does_not_have_fires_nothing(client, admin_id, member_id):
    """On a board of its own, so the scenario's own rule is not the thing
    being measured — a status key nobody has is a rule that never matches."""
    bid = client.post("/api/boards", json={"name": "בקשות סטטוס זר",
                                           "user_id": admin_id}).json()["id"]
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": "status_create_subitem",
                          "config": {"t_status": "x_nonesuch", "a_text": "ביצוע"}})
    assert r.status_code == 200, r.text
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "בקשה",
                                          "user_id": admin_id}).json()["id"]
    for st in ("done", "in_progress", "x_nonesuch"):
        client.patch(f"/api/tasks/{tid}", json={"status": st, "user_id": admin_id})
    assert _subs(tid) == [], "a rule listening for a status nobody has fired"


def test_a_person_who_is_not_on_the_board_cannot_be_assigned(client, admin_id, guinea_id):
    bid = client.post("/api/boards", json={"name": "בקשות אחראי זר",
                                           "user_id": admin_id}).json()["id"]
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": "status_assign_person",
                          "config": {"t_status": "done", "a_person": guinea_id}})
    assert r.status_code >= 400, r.text


def test_an_editor_cannot_write_the_rule(client, admin_id, member_id):
    bid, _ = _scenario(client, admin_id, member_id, "בקשות הרשאה")
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": member_id, "recipe_id": "status_create_subitem",
                          "config": {"t_status": APPROVED, "a_text": "ביצוע"}})
    assert r.status_code == 403, r.text


def test_a_second_rule_on_the_same_field_is_warned_about(client, admin_id, member_id):
    """«התנגשויות» — two rules writing one field is a thing somebody may mean.
    What it must not be is a surprise."""
    bid, _ = _scenario(client, admin_id, member_id, "בקשות התנגשות")
    other = client.post(f"/api/boards/{bid}/automations",
                        json={"actor_id": admin_id, "recipe_id": "status_assign_person",
                              "config": {"t_status": APPROVED, "a_person": admin_id}},
                        ).json()
    client.patch(f"/api/automations/{other['id']}?user_id={admin_id}",
                 json={"status": "paused"})
    r = client.patch(f"/api/automations/{other['id']}?user_id={admin_id}",
                     json={"status": "active"})
    assert r.status_code == 200, r.text
    warn = r.json().get("warnings") or []
    assert any("אחראי" in (w.get("text") or "") or "שדות" in (w.get("text") or "")
               for w in warn), warn


def test_a_dry_run_says_what_would_happen_and_changes_nothing(client, admin_id, member_id):
    bid, rule = _scenario(client, admin_id, member_id, "בקשות בדיקה")
    tid = _request(client, bid, admin_id, "בדיקה יבשה")
    d = client.post(f"/api/automations/{rule['id']}/test?user_id={admin_id}",
                    json={"task_id": tid})
    assert d.status_code == 200, d.text
    got = d.json()
    assert got["changed_nothing"] is True and got["notified_nobody"] is True
    assert got["verdict"] in ("would_run", "blocked", "would_skip"), got
    assert _subs(tid) == [], "a dry run created the sub-item for real"
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert [u.id for u in t.assignees] == []


# ── 3. פרסום אירוע אחרי השמירה ─────────────────────────────────────────────

def test_the_event_goes_out_after_the_status_has_landed(client, admin_id, member_id,
                                                        monkeypatch):
    bid, _ = _scenario(client, admin_id, member_id, "בקשות פרסום")
    tid = _request(client, bid, admin_id, "בקשה")
    seen = []
    real = cityos_main.bus.publish

    def spy(kind, **kw):
        if kind == "task.changed":
            with Session(cityos_main.engine) as db:
                t = db.query(Task).filter(Task.id == kw.get("task_id")).first()
                seen.append((cityos_main._task_status_key(t) if t else None,
                             len(_subs(tid))))
        return real(kind, **kw)
    monkeypatch.setattr(cityos_main.bus, "publish", spy)
    _approve(client, tid, admin_id)
    monkeypatch.undo()
    assert seen, "nothing was published"
    assert seen[-1] == (APPROVED, 1), \
        f"the event went out before the write had landed: {seen[-1]}"


def test_the_business_event_is_durable(client, admin_id, member_id):
    bid, rule = _scenario(client, admin_id, member_id, "בקשות אאוטבוקס")
    tid = _request(client, bid, admin_id, "בקשה")
    _approve(client, tid, admin_id)
    with Session(cityos_main.engine) as db:
        rows = (db.query(EventOutbox)
                  .filter(EventOutbox.board_id == bid, EventOutbox.task_id == tid)
                  .order_by(EventOutbox.id).all())
    assert rows and rows[-1].kind == "automation.ran", [r.kind for r in rows]
    assert rows[-1].automation_id == rule["id"]
    assert [r.seq for r in rows] == list(range(1, len(rows) + 1))


# ── 4. הסדר, והתיעוד של כל שלב ─────────────────────────────────────────────

def test_the_three_actions_are_logged_in_the_order_they_ran(client, admin_id, member_id):
    bid, _ = _scenario(client, admin_id, member_id, "בקשות סדר")
    tid = _request(client, bid, admin_id, "בקשה")
    _approve(client, tid, admin_id)
    run = [r for r in _runs(client, bid, admin_id) if r["outcome"] == "ran"][0]
    steps = (run["result"] or {}).get("steps") or []
    assert [s["key"] for s in steps] == ["create_subitem", "assign_person", "post_update"], \
        [s["key"] for s in steps]
    assert [s["index"] for s in steps] == [1, 2, 3], steps
    assert all(s["status"] == "succeeded" for s in steps), steps
    assert all("input" in s and "target" in s and "output" in s for s in steps)


def test_the_run_row_carries_the_whole_story(client, admin_id, member_id):
    bid, rule = _scenario(client, admin_id, member_id, "בקשות שורה")
    tid = _request(client, bid, admin_id, "בקשה")
    _approve(client, tid, admin_id)
    run = [r for r in _runs(client, bid, admin_id) if r["outcome"] == "ran"][0]
    assert run["status"] == "succeeded"
    assert run["automation_id"] == rule["id"] and run["version"]
    assert run["task_id"] == tid
    assert run["queued_at"] <= run["started_at"] <= run["finished_at"]
    assert (run["result"] or {}).get("old") and (run["result"] or {}).get("new") == APPROVED
    conds = (run["result"] or {}).get("conditions") or []
    assert conds and conds[0]["held"] is True, conds
    assert run["chain_id"] and run["ref"], run


def test_the_timeline_reads_as_the_scenario(client, admin_id, member_id):
    bid, _ = _scenario(client, admin_id, member_id, "בקשות ציר")
    tid = _request(client, bid, admin_id, "בקשה")
    _approve(client, tid, admin_id)
    run = [r for r in _runs(client, bid, admin_id) if r["outcome"] == "ran"][0]
    d = client.get(f"/api/automation-runs/{run['id']}/timeline?user_id={admin_id}")
    assert d.status_code == 200, d.text
    kinds = [s["kind"] for s in d.json()["timeline"]]
    assert kinds[0] == "event" and kinds[-1] == "end"
    assert kinds.count("action") == 3 and "condition" in kinds, kinds


def test_the_items_own_log_names_the_rule(client, admin_id, member_id):
    bid, _ = _scenario(client, admin_id, member_id, "בקשות לוג פריט")
    tid = _request(client, bid, admin_id, "בקשה")
    _approve(client, tid, admin_id)
    sub = _subs(tid)[0]
    rows = client.get(f"/api/tasks/{sub.id}/activity",
                      headers=AS(admin_id)).json()["activity"]
    mine = [r for r in rows if r.get("origin") == "automation"]
    assert mine, [(r["field"], r["user_name"]) for r in rows]
    assert "בקשה שאושרה" in (mine[0]["user_name"] or ""), mine[0]


# ── 5. כשל זמני: המשך מהפעולה שנכשלה ───────────────────────────────────────

def test_a_temporary_failure_resumes_where_it_stopped(client, admin_id, member_id,
                                                      monkeypatch):
    """The sub-item was created and the person was assigned. The update blew
    up. A retry finishes the update and does NOT make a second sub-item."""
    bid, _ = _scenario(client, admin_id, member_id, "בקשות כשל זמני")
    real = cityos_main._post_automation_update if hasattr(
        cityos_main, "_post_automation_update") else None
    calls = {"n": 0}
    inner = cityos_main._run_one_action

    def flaky(db, act, cfg, task, *a, **kw):
        if act == "post_update":
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("database is locked")
        return inner(db, act, cfg, task, *a, **kw)
    monkeypatch.setattr(cityos_main, "_run_one_action", flaky)
    tid = _request(client, bid, admin_id, "בקשה שנתקעה")
    _approve(client, tid, admin_id)

    assert len(_subs(tid)) == 1, "the first two actions were rolled back"
    assert _updates(tid) == [], "the third action was not the one that failed"
    first = [r for r in _runs(client, bid, admin_id) if r["status"] == "failed_temporary"]
    assert first, [r["status"] for r in _runs(client, bid, admin_id)]
    steps = (first[0]["result"] or {}).get("steps") or []
    assert [s["status"] for s in steps] == ["succeeded", "succeeded", "failed_temporary"]

    # the automatic retry, brought forward
    with Session(cityos_main.engine) as db:
        back = datetime.now(timezone.utc) - timedelta(minutes=1)
        for q in db.query(AutomationQueue).filter(
                AutomationQueue.board_id == bid,
                AutomationQueue.done_at == None).all():               # noqa: E711
            q.event = {**(q.event or {}), "after": back.isoformat()}
            q.resume_at = back.replace(tzinfo=None)
        db.commit()
    client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}")
    monkeypatch.undo()

    assert len(_subs(tid)) == 1, "the retry created a second sub-item"
    assert any("הבקשה אושרה" in c for c in _updates(tid)), "the retry never finished it"
    second = [r for r in _runs(client, bid, admin_id) if r["attempt"] == 2]
    assert second, [r["attempt"] for r in _runs(client, bid, admin_id)]
    began = ((second[0]["result"] or {}).get("steps") or [{}])[0].get("index")
    assert began == 3, f"the retry started at action {began} instead of 3"


# ── 6. כשל קבוע: התראה לבעלים ─────────────────────────────────────────────

def test_a_permanent_failure_reaches_the_owner(client, admin_id, member_id, monkeypatch):
    bid, rule = _scenario(client, admin_id, member_id, "בקשות כשל קבוע")
    inner = cityos_main._run_one_action

    def refused(db, act, cfg, task, *a, **kw):
        if act == "assign_person":
            raise cityos_main._Refused("האחראי אינו חבר בלוח עוד")
        return inner(db, act, cfg, task, *a, **kw)
    monkeypatch.setattr(cityos_main, "_run_one_action", refused)
    with Session(cityos_main.engine) as db:
        before = db.query(Notification).filter(
            Notification.user_id == admin_id,
            Notification.type == "automation").count()
    tid = _request(client, bid, admin_id, "בקשה שנופלת")
    _approve(client, tid, admin_id)
    monkeypatch.undo()

    run = [r for r in _runs(client, bid, admin_id)][0]
    assert run["status"] == "failed_permanent", run
    assert run["error_code"] == "refused", run
    with Session(cityos_main.engine) as db:
        after = db.query(Notification).filter(
            Notification.user_id == admin_id,
            Notification.type == "automation").count()
        inc = (db.query(AutomationIncident)
                 .filter(AutomationIncident.automation_id == rule["id"]).all())
    assert after > before, "the owner was not told"
    assert inc and inc[0].status == "open", inc
    # and nothing was sent round again — the engine would decide the same thing
    with Session(cityos_main.engine) as db:
        assert not [q for q in db.query(AutomationQueue)
                    .filter(AutomationQueue.board_id == bid,
                            AutomationQueue.done_at == None).all()     # noqa: E711
                    if (q.event or {}).get("type") == "retry"]


def test_making_a_subitem_cannot_make_another_forever(client, admin_id, member_id):
    """The sub-item a rule creates now announces itself, the way one created
    by hand always has — which puts "כאשר נוצר תת־פריט, צור תת־פריט" one step
    from an infinite board. It is one step and no further: the rule has
    already run on this parent in this chain."""
    bid = client.post("/api/boards", json={"name": "בקשות תת-פריט חוזר",
                                           "user_id": admin_id}).json()["id"]
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": "subitem_created_set_status",
                          "config": {"a_status": "in_progress"}})
    assert r.status_code == 200, r.text
    r2 = client.post(f"/api/boards/{bid}/automations",
                     json={"actor_id": admin_id, "recipe_id": "status_create_subitem",
                           "config": {"t_status": "in_progress", "a_text": "עוד"}})
    assert r2.status_code == 200, r2.text
    parent = client.post("/api/tasks", json={"board_id": bid, "title": "אב",
                                             "user_id": admin_id}).json()["id"]
    client.post("/api/tasks", json={"board_id": bid, "title": "תת",
                                    "user_id": admin_id, "parent_id": parent})
    kids = _subs(parent)
    assert len(kids) <= 3, [k.title for k in kids]


def test_the_whole_scenario_is_in_the_audit(client, admin_id, member_id):
    bid, rule = _scenario(client, admin_id, member_id, "בקשות אודיט")
    tid = _request(client, bid, admin_id, "בקשה")
    client.post(f"/api/automations/{rule['id']}/test?user_id={admin_id}",
                json={"task_id": tid})
    _approve(client, tid, admin_id)
    rows = client.get(f"/api/boards/{bid}/automations/audit?user_id={admin_id}"
                      ).json()["audit"]
    acts = [r["action"] for r in rows]
    assert "create" in acts and "dry_run" in acts, acts
