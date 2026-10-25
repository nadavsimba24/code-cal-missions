"""Group — כשלים וניסיון חוזר: trying again without doing it twice.

A retry is easy to get wrong in exactly two directions and both of them are
expensive. Too little: a rule that hit a locked row at three in the morning is
dead until somebody notices, and nobody notices. Too much: a rule that created
an item and then failed on its fourth action creates a second item every time
anybody presses "נסה שוב".

So four things hold it together:

  זמני מול קבוע · a lock is worth trying again, a deleted group is not, and the
                  engine must know which it is looking at before it decides
  1, 5, 15      · three automatic attempts, spaced so a short outage is ridden
                  out and a long one is not hammered
  מהנקודה       · a retry starts at the action that failed. The three before it
                  worked, and a retry is not a second chance to do them again
  מפתח          · and underneath that, a key per action, so even a retry aimed
                  at the wrong place cannot send the notification twice

And "הפעלה מחדש מההתחלה" is not a retry at all — it is a new run with a new id,
and it says so before it does it.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AutomationQueue, AutomationRun, Comment, Task

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


def _runs(client, bid, admin_id, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}{qs}"
                      ).json()["runs"]


def _queued(bid, kind="retry"):
    with Session(cityos_main.engine) as db:
        return [r for r in db.query(AutomationQueue)
                .filter(AutomationQueue.board_id == bid,
                        AutomationQueue.done_at == None).all()          # noqa: E711
                if (r.event or {}).get("type") == kind]


def _due_now(bid):
    """Bring every queued retry forward so the next board read picks it up."""
    with Session(cityos_main.engine) as db:
        back = datetime.now(timezone.utc) - timedelta(minutes=1)
        for r in db.query(AutomationQueue).filter(AutomationQueue.board_id == bid,
                                                  AutomationQueue.done_at == None).all():
            r.event = {**(r.event or {}), "after": back.isoformat()}
            r.resume_at = back.replace(tzinfo=None)
        db.commit()


def _poke(client, bid, admin_id):
    """Make the queue move. The board read drains it too, but under a rate
    limit — this is the screen asking, which is a deliberate step."""
    client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}")


class _Flaky:
    """Fails the first n times it is called, then works."""

    def __init__(self, real, n):
        self.real, self.left = real, n

    def __call__(self, *a, **kw):
        if self.left > 0:
            self.left -= 1
            raise RuntimeError("database is locked")
        return self.real(*a, **kw)


# ── זמני מול קבוע ──────────────────────────────────────────────────────────

def test_the_delays_are_the_ones_the_spec_names(client, admin_id):
    assert cityos_main.AUTOMATION_RETRY_DELAYS == (1, 5, 15)
    assert cityos_main.AUTOMATION_MAX_AUTO_RETRIES == 3


def test_a_temporary_failure_is_queued_for_another_go(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח זמני חוזר")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    monkeypatch.setattr(cityos_main, "_apply_priority_key",
                        _Flaky(cityos_main._apply_priority_key, 99))
    _item(client, bid, admin_id)
    monkeypatch.undo()
    q = _queued(bid)
    assert len(q) == 1, q
    assert (q[0].event or {}).get("attempt") == 2, q[0].event
    due = q[0].resume_at.replace(tzinfo=timezone.utc)
    assert timedelta(seconds=30) < (due - datetime.now(timezone.utc)) <= timedelta(minutes=1)


def test_a_permanent_failure_is_not(client, admin_id):
    """A refusal is a decision the engine made on what it read. It will make
    the same one in a minute, and in five, and in fifteen."""
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
    assert _runs(client, a, admin_id)[0]["status"] == "failed_permanent"
    assert _queued(a) == [], "a permanent failure was sent round again"


def test_three_attempts_and_then_it_stops(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח שלושה")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    flaky = _Flaky(cityos_main._apply_priority_key, 99)
    monkeypatch.setattr(cityos_main, "_apply_priority_key", flaky)
    _item(client, bid, admin_id)
    for _ in range(5):                      # more pokes than there are attempts
        _due_now(bid)
        _poke(client, bid, admin_id)
    monkeypatch.undo()
    tries = sorted(r["attempt"] for r in _runs(client, bid, admin_id)
                   if r["status"] == "failed_temporary")
    assert tries == [1, 2, 3, 4], tries   # the first go plus three retries
    assert _queued(bid) == [], "it is still going round"


def test_an_attempt_that_works_ends_the_chain(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח הצליח בסוף")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    monkeypatch.setattr(cityos_main, "_apply_priority_key",
                        _Flaky(cityos_main._apply_priority_key, 1))
    tid = _item(client, bid, admin_id)
    _due_now(bid)
    _poke(client, bid, admin_id)
    monkeypatch.undo()
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._task_priority_key(t) == "high"
    assert any(r["status"] == "succeeded" and r["attempt"] == 2
               for r in _runs(client, bid, admin_id)), _runs(client, bid, admin_id)
    assert _queued(bid) == []


# ── מתחיל בפעולה שנכשלה ───────────────────────────────────────────────────

def _three_steps(client, bid, admin_id):
    """Set priority, post an update, then set a status — three visible marks."""
    return _add(client, bid, admin_id, "created_set_priority",
                {"a_priority": "high",
                 "actions": [{"key": "post_update", "values": {"text": "שלב שני"}},
                             {"key": "set_status", "values": {"status": "in_progress"}}]})


def _updates(tid):
    with Session(cityos_main.engine) as db:
        return db.query(Comment).filter(Comment.task_id == tid).count()


def test_a_retry_starts_at_the_action_that_failed(client, admin_id, monkeypatch):
    """The two before it worked. A retry is not a second chance to do them."""
    bid = _board(client, admin_id, "לוח מהנקודה")
    _three_steps(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "_apply_status_key",
                        _Flaky(cityos_main._apply_status_key, 1))
    tid = _item(client, bid, admin_id)
    assert _updates(tid) == 1, "the second action did not run the first time"
    _due_now(bid)
    _poke(client, bid, admin_id)
    monkeypatch.undo()
    assert _updates(tid) == 1, "the retry posted the update a second time"
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._task_status_key(t) == "in_progress", "the retry never finished it"


def test_the_log_says_where_the_retry_picked_up(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח נקודת פתיחה")
    _three_steps(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "_apply_status_key",
                        _Flaky(cityos_main._apply_status_key, 1))
    _item(client, bid, admin_id)
    _due_now(bid)
    _poke(client, bid, admin_id)
    monkeypatch.undo()
    second = [r for r in _runs(client, bid, admin_id) if r["attempt"] == 2]
    assert second, [r["attempt"] for r in _runs(client, bid, admin_id)]
    steps = (second[0]["result"] or {}).get("steps") or []
    assert steps and steps[0]["index"] == 3, steps


# ── מפתח Idempotency לכל פעולה ───────────────────────────────────────────

def test_an_action_that_already_worked_does_not_work_twice(client, admin_id):
    """The belt under the braces. Even a retry aimed at the wrong action — a
    replayed event, a double click, a bug — cannot post the update again."""
    bid = _board(client, admin_id, "לוח מפתח")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "post_update", "values": {"text": "פעם אחת"}}]})
    tid = _item(client, bid, admin_id)
    assert _updates(tid) == 1
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        run = (db.query(AutomationRun).filter(AutomationRun.task_id == tid)
                 .order_by(AutomationRun.id.desc()).first())
        # the very same event, chain and all, fed through a second time
        cityos_main._run_automations(db, t, dict(run.event, id="again"), admin_id)
        db.commit()
    assert _updates(tid) == 1, "the update was posted twice"


def test_a_genuinely_new_event_is_not_blocked_by_the_key(client, admin_id):
    """The key is scoped to one chain. A second, real change has to get through
    or the guard would make every rule a once-per-item rule."""
    bid = _board(client, admin_id, "לוח מפתח חדש")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "actions": [{"key": "post_update", "values": {"text": "שוב"}}]})
    tid = _item(client, bid, admin_id)
    for _ in range(2):
        client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
        client.patch(f"/api/tasks/{tid}", json={"status": "todo", "user_id": admin_id})
    assert _updates(tid) == 2, "a real second change was swallowed by the key"


def test_the_key_is_on_the_step(client, admin_id):
    bid = _board(client, admin_id, "לוח מפתח בלוג")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    steps = (_runs(client, bid, admin_id)[0]["result"] or {}).get("steps") or []
    assert steps and steps[0].get("key_id"), steps
    assert len({s["key_id"] for s in steps}) == len(steps), "two actions share a key"


# ── Retry ידני ────────────────────────────────────────────────────────────

def test_the_plan_says_what_is_left(client, admin_id, monkeypatch):
    """«Retry ידני יציג את הפעולות שנותרו ויחייב אישור»."""
    bid = _board(client, admin_id, "לוח תוכנית")
    _three_steps(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "_apply_status_key",
                        _Flaky(cityos_main._apply_status_key, 99))
    _item(client, bid, admin_id)
    monkeypatch.undo()
    run = [r for r in _runs(client, bid, admin_id) if r["status"] == "failed_temporary"][0]
    d = client.get(f"/api/automation-runs/{run['id']}/retry-plan?user_id={admin_id}")
    assert d.status_code == 200, d.text
    plan = d.json()
    assert plan["from_index"] == 3, plan
    assert [x["index"] for x in plan["remaining"]] == [3], plan
    assert [x["index"] for x in plan["done"]] == [1, 2], plan
    assert plan["can_retry"] is True
    assert plan["restart_warning"], "nothing warns about running the whole thing again"


def test_the_plan_is_closed_to_somebody_who_may_not_manage(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח תוכנית סגורה")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    _add(client, bid, admin_id, "created_set_status",
         {"a_status": "done", "conditions": [{"kind": "has_assignee", "value": True}]})
    _item(client, bid, admin_id)
    run = _runs(client, bid, admin_id)[0]
    assert client.get(f"/api/automation-runs/{run['id']}/retry-plan?user_id={guinea_id}"
                      ).status_code == 403


def test_a_manual_retry_also_starts_where_it_stopped(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח ידני")
    _three_steps(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "_apply_status_key",
                        _Flaky(cityos_main._apply_status_key, 99))
    tid = _item(client, bid, admin_id)
    monkeypatch.undo()
    run = [r for r in _runs(client, bid, admin_id) if r["status"] == "failed_temporary"][0]
    r = client.post(f"/api/automation-runs/{run['id']}/retry?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert _updates(tid) == 1, "the manual retry repeated an action that had worked"
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._task_status_key(t) == "in_progress"


def test_running_it_again_from_the_start_is_a_separate_thing(client, admin_id, monkeypatch):
    """«הפעלה מחדש מההתחלה היא פעולה נפרדת עם מזהה חדש ואזהרת השפעה כפולה» —
    a new chain, so the keys do not hold it back, and it really does do the
    whole rule over. Which is exactly why it is not the default."""
    bid = _board(client, admin_id, "לוח מההתחלה")
    _three_steps(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "_apply_status_key",
                        _Flaky(cityos_main._apply_status_key, 99))
    tid = _item(client, bid, admin_id)
    monkeypatch.undo()
    run = [r for r in _runs(client, bid, admin_id) if r["status"] == "failed_temporary"][0]
    r = client.post(f"/api/automation-runs/{run['id']}/retry"
                    f"?user_id={admin_id}&from_start=true&confirm=true")
    assert r.status_code == 200, r.text
    assert _updates(tid) == 2, "running it from the start did not run it from the start"
    made = r.json()["run"]
    assert made["chain_id"] and made["chain_id"] != run["chain_id"], \
        "a restart reused the original chain"


def test_running_it_again_from_the_start_needs_saying_so(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח אישור")
    _three_steps(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "_apply_status_key",
                        _Flaky(cityos_main._apply_status_key, 99))
    _item(client, bid, admin_id)
    monkeypatch.undo()
    run = [r for r in _runs(client, bid, admin_id) if r["status"] == "failed_temporary"][0]
    r = client.post(f"/api/automation-runs/{run['id']}/retry"
                    f"?user_id={admin_id}&from_start=true")
    assert r.status_code == 400, r.text
    assert "כפול" in r.json()["detail"] or "מההתחלה" in r.json()["detail"], r.json()


def test_only_a_manager_may_retry(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח הרשאת retry")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    _add(client, bid, admin_id, "created_set_status",
         {"a_status": "done", "conditions": [{"kind": "has_assignee", "value": True}]})
    _item(client, bid, admin_id)
    run = _runs(client, bid, admin_id)[0]
    assert client.post(f"/api/automation-runs/{run['id']}/retry?user_id={guinea_id}"
                       ).status_code == 403


# ── השהיה אוטומטית ────────────────────────────────────────────────────────

def test_a_failure_rate_over_the_threshold_suspends_it(client, admin_id, monkeypatch):
    """«שיעור כשלים מעל הסף» — a RATE, which is a different thing from five in
    a row. A rule that fails two runs in three is broken even though it keeps
    getting the occasional one through."""
    bid = _board(client, admin_id, "לוח שיעור")
    rule = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    real = cityos_main._apply_priority_key
    n = {"i": 0}

    def flappy(*a, **kw):
        n["i"] += 1
        if n["i"] % 3:                       # two out of every three blow up
            raise RuntimeError("database is locked")
        return real(*a, **kw)
    monkeypatch.setattr(cityos_main, "_apply_priority_key", flappy)
    for i in range(cityos_main.AUTOMATION_FAIL_RATE_MIN + 3):
        _item(client, bid, admin_id, f"פריט {i}")
    monkeypatch.undo()
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == rule["id"]).first()
        assert row.status == "paused_error", row.status


def test_a_rule_that_mostly_works_is_left_alone(client, admin_id, monkeypatch):
    """The threshold has to be a threshold. One bad run in twenty is a system
    having a bad moment, not a rule that needs taking out of service."""
    bid = _board(client, admin_id, "לוח כמעט תקין")
    rule = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    real = cityos_main._apply_priority_key
    n = {"i": 0}

    def rare(*a, **kw):
        n["i"] += 1
        if n["i"] == 2:
            raise RuntimeError("database is locked")
        return real(*a, **kw)
    monkeypatch.setattr(cityos_main, "_apply_priority_key", rare)
    for i in range(cityos_main.AUTOMATION_FAIL_RATE_MIN + 5):
        _item(client, bid, admin_id, f"פריט {i}")
    monkeypatch.undo()
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == rule["id"]).first()
        assert row.status == "active", row.status


def test_the_threshold_is_published(client, admin_id):
    d = client.get(f"/api/automation-capabilities?user_id={admin_id}").json()
    assert d["retry"]["delays"] == [1, 5, 15]
    assert d["retry"]["max_auto"] == 3
    assert d["retry"]["fail_rate"] == cityos_main.AUTOMATION_FAIL_RATE


def test_a_suspended_rule_stops_being_retried_automatically(client, admin_id, monkeypatch):
    """Once it is out of service, going on trying is noise: the queue would
    keep firing a rule somebody has already been told to look at."""
    bid = _board(client, admin_id, "לוח מושהה חוזר")
    rule = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    monkeypatch.setattr(cityos_main, "_apply_priority_key",
                        _Flaky(cityos_main._apply_priority_key, 99))
    _item(client, bid, admin_id)
    monkeypatch.undo()
    assert _queued(bid), "nothing was queued to begin with"
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == rule["id"]).first()
        cityos_main._set_automation_status(a, "paused")
        db.commit()
    _due_now(bid)
    _poke(client, bid, admin_id)
    assert _queued(bid) == [], "a paused rule was still being retried"
