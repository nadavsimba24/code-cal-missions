"""Group — ארכיטקטורה, ביצועים וניטור: nothing lost, nothing out of order.

The live path is an in-memory fan-out to whoever has a stream open. It is the
right thing for a screen and the wrong thing for a record: an event raised
while the loop is shutting down, or while nobody is listening, is simply gone,
and the write it was announcing has already been committed. A board that
missed the announcement looks exactly like a board where nothing happened.

So the module's business events are written in the SAME transaction as the
change, and sent afterwards. If the process dies in between, the next drain
sends them — at-least-once, which is why every consumer has an idempotency key
to make the second delivery harmless. Per item they keep their order, because
"moved to done" then "moved back" and the reverse are different stories.

And the parts somebody has to be able to see: what is queued, what is held,
what died, how close the organisation is to its allowance, and how long the
rules are actually taking.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import (Automation, AutomationQueue, AutomationRun, EventOutbox,
                    Organization, Task)

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title="פריט", **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **kw}).json()["id"]


def _add(client, bid, admin_id, recipe_id="created_set_priority", config=None, **extra):
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": recipe_id,
                          "config": config or {"a_priority": "high"}, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _outbox(bid, **f):
    with Session(cityos_main.engine) as db:
        q = db.query(EventOutbox).filter(EventOutbox.board_id == bid)
        for k, v in f.items():
            q = q.filter(getattr(EventOutbox, k) == v)
        return q.order_by(EventOutbox.id).all()


def _health(client, admin_id):
    r = client.get(f"/api/admin/automations/health?user_id={admin_id}")
    assert r.status_code == 200, r.text
    return r.json()


# ── Outbox: נכתב עם השינוי, נשלח אחריו ────────────────────────────────────

def test_a_run_writes_a_business_event_in_the_same_transaction(client, admin_id):
    bid = _board(client, admin_id, "לוח אאוטבוקס")
    a = _add(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    rows = _outbox(bid)
    assert rows, "the run announced nothing durably"
    one = rows[-1]
    assert one.kind == "automation.ran"
    assert one.task_id == tid and one.automation_id == a["id"]
    assert one.created_at is not None


def test_the_event_is_sent_and_marked(client, admin_id):
    bid = _board(client, admin_id, "לוח נשלח")
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    rows = _outbox(bid)
    assert rows and all(r.sent_at is not None for r in rows), \
        [(r.id, r.kind, r.sent_at) for r in rows]


def test_an_event_the_process_never_sent_goes_out_next_time(client, admin_id):
    """The whole reason the table exists: the write landed and the
    announcement did not, and nothing but a durable row can tell."""
    bid = _board(client, admin_id, "לוח אובדן")
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:                  # pretend it died
        for r in db.query(EventOutbox).filter(EventOutbox.board_id == bid).all():
            r.sent_at, r.attempts = None, 0
        db.commit()
    sent = []
    real = cityos_main.bus.publish
    try:
        cityos_main.bus.publish = lambda kind, **kw: sent.append(kind)
        with Session(cityos_main.engine) as db:
            cityos_main._drain_outbox(db, bid)
            db.commit()
    finally:
        cityos_main.bus.publish = real
    assert "automation.ran" in sent, sent
    assert all(r.sent_at is not None for r in _outbox(bid))


def test_a_second_drain_does_not_send_it_twice(client, admin_id):
    bid = _board(client, admin_id, "לוח פעמיים")
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    sent = []
    real = cityos_main.bus.publish
    try:
        cityos_main.bus.publish = lambda kind, **kw: sent.append(kind)
        for _ in range(3):
            with Session(cityos_main.engine) as db:
                cityos_main._drain_outbox(db, bid)
                db.commit()
    finally:
        cityos_main.bus.publish = real
    assert sent.count("automation.ran") <= 1, sent


def test_events_for_one_item_keep_their_order(client, admin_id):
    """«שמירת סדר אירועים לכל פריט» — "moved to done" then "moved back" and
    the other way round are different stories about the same item."""
    bid = _board(client, admin_id, "לוח סדר אירועים")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "todo", "a_priority": "low"})
    tid = _item(client, bid, admin_id)
    for st in ("done", "todo", "done"):
        client.patch(f"/api/tasks/{tid}", json={"status": st, "user_id": admin_id})
    mine = [r for r in _outbox(bid) if r.task_id == tid]
    assert len(mine) >= 3, mine
    assert [r.seq for r in mine] == sorted(r.seq for r in mine), [r.seq for r in mine]
    assert [r.seq for r in mine] == list(range(1, len(mine) + 1)), [r.seq for r in mine]


def test_two_items_have_their_own_sequences(client, admin_id):
    bid = _board(client, admin_id, "לוח שני רצפים")
    _add(client, bid, admin_id)
    a, b = _item(client, bid, admin_id, "א"), _item(client, bid, admin_id, "ב")
    for t in (a, b):
        assert [r.seq for r in _outbox(bid) if r.task_id == t] == [1], t


def test_an_event_that_cannot_go_out_ends_in_the_dead_letter_queue(client, admin_id):
    bid = _board(client, admin_id, "לוח DLQ")
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        for r in db.query(EventOutbox).filter(EventOutbox.board_id == bid).all():
            r.sent_at, r.attempts = None, cityos_main.OUTBOX_MAX_ATTEMPTS
        db.commit()
    real = cityos_main.bus.publish

    def boom(kind, **kw):
        raise RuntimeError("bus down")
    try:
        cityos_main.bus.publish = boom
        with Session(cityos_main.engine) as db:
            cityos_main._drain_outbox(db, bid)
            db.commit()
    finally:
        cityos_main.bus.publish = real
    dead = [r for r in _outbox(bid) if r.dead_at is not None]
    assert dead, [(r.id, r.attempts, r.sent_at) for r in _outbox(bid)]
    assert _health(client, admin_id)["outbox"]["dead"] >= 1


# ── עמידות: כלום לא יושב בזיכרון ה-Worker ─────────────────────────────────

def test_a_wait_survives_a_restart(client, admin_id):
    """«שמור משימות והשהיות באחסון עמיד» — a wait that lived in memory would
    be lost on every deploy, which is most of what a thirty-day wait sees."""
    bid = _board(client, admin_id, "לוח עמידות")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "wait", "values": {"days": 60}},
                      {"key": "post_update", "values": {"text": "אחרי"}}]})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:        # a fresh session is a fresh process
        row = (db.query(AutomationQueue)
                 .filter(AutomationQueue.task_id == tid,
                         AutomationQueue.done_at == None).first())    # noqa: E711
        assert row is not None
        assert row.resume_at is not None and row.automation_id and row.version


# ── מכסות ──────────────────────────────────────────────────────────────────

def _set_quota(client, admin_id, **q):
    r = client.patch(f"/api/organization/settings?user_id={admin_id}",
                     json={"quota": q})
    assert r.status_code == 200, r.text
    return r.json()["quota"]


def test_the_quota_is_configurable_per_organisation(client, admin_id):
    got = _set_quota(client, admin_id, monthly_runs=500)
    assert got["monthly_runs"] == 500
    assert _health(client, admin_id)["quota"]["limit"] == 500
    # and null puts it back on the default, rather than pinning it to 500
    assert _set_quota(client, admin_id, monthly_runs=None)["monthly_runs"] \
        == cityos_main.AUTOMATION_MONTHLY_QUOTA
    _set_quota(client, admin_id, monthly_runs=None, enforce=False)


def test_eighty_percent_is_a_warning_and_not_a_wall(client, admin_id):
    bid = _board(client, admin_id, "לוח אזהרה")
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        used = cityos_main._automation_quota(db)["used"]
    _set_quota(client, admin_id, monthly_runs=max(2, int(used / 0.85)), enforce=False)
    h = _health(client, admin_id)
    assert h["quota"]["warn_at"] == 0.8
    assert h["quota"]["warning"] is True, h["quota"]
    assert h["quota"]["blocked"] is False, "a warning stopped the work"
    _item(client, bid, admin_id, "עוד")             # still runs
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.title == "עוד", Task.board_id == bid).first()
        assert cityos_main._task_priority_key(t) == "high"
    _set_quota(client, admin_id, monthly_runs=None, enforce=False)


def test_over_the_quota_the_work_is_deferred_and_not_dropped(client, admin_id):
    """«ניהול עומסים ללא אובדן אירועים» — over the allowance the event waits
    its turn. It does not vanish, and the board is not quietly un-automated."""
    bid = _board(client, admin_id, "לוח מעל המכסה")
    _add(client, bid, admin_id)
    _set_quota(client, admin_id, monthly_runs=1, enforce=True)
    tid = _item(client, bid, admin_id, "נדחה")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._task_priority_key(t) != "high", "it ran over the quota"
        held = [r for r in db.query(AutomationQueue)
                .filter(AutomationQueue.board_id == bid,
                        AutomationQueue.done_at == None).all()        # noqa: E711
                if (r.event or {}).get("type") not in ("resume", "retry")]
    assert held, "the event was dropped rather than deferred"
    assert _health(client, admin_id)["quota"]["blocked"] is True
    _set_quota(client, admin_id, monthly_runs=None, enforce=False)


def test_enforcement_is_off_unless_the_organisation_asks(client, admin_id):
    """The old reading stands by default: a hard stop in the middle of a month
    quietly breaks the boards that depend on rules."""
    bid = _board(client, admin_id, "לוח ללא אכיפה")
    _add(client, bid, admin_id)
    _set_quota(client, admin_id, monthly_runs=1, enforce=False)
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._task_priority_key(t) == "high"
    _set_quota(client, admin_id, monthly_runs=None, enforce=False)


# ── ניטור ──────────────────────────────────────────────────────────────────

def test_the_health_endpoint_covers_what_the_section_lists(client, admin_id):
    h = _health(client, admin_id)
    for key in ("queue", "outbox", "retry", "waits", "loops", "incidents",
                "quota", "performance"):
        assert key in h, (key, sorted(h))
    for key in ("pending", "frozen", "cancelled", "dead"):
        assert key in h["queue"], h["queue"]
    for key in ("ran", "skipped", "failed", "success_rate"):
        assert key in h["performance"], h["performance"]


def test_the_performance_numbers_are_real(client, admin_id):
    bid = _board(client, admin_id, "לוח ביצועים")
    _add(client, bid, admin_id)
    for i in range(3):
        _item(client, bid, admin_id, f"פריט {i}")
    p = _health(client, admin_id)["performance"]
    assert p["ran"] >= 3, p
    assert p["p50_ms"] is not None and p["p50_ms"] >= 0, p
    assert p["p95_ms"] is not None and p["p95_ms"] >= p["p50_ms"], p


def test_a_loop_cut_is_counted(client, admin_id):
    bid = _board(client, admin_id, "לוח ספירת לולאות")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    before = _health(client, admin_id)["loops"]["stopped"]
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        cityos_main._run_automations(
            db, t, cityos_main._event("status_changes_to", "item", status="done",
                                      chain_runs=cityos_main.AUTOMATION_CHAIN_MAX_RUNS),
            admin_id)
        db.commit()
    assert _health(client, admin_id)["loops"]["stopped"] > before


def test_health_is_for_a_system_administrator_only(client, admin_id, guinea_id):
    assert client.get(f"/api/admin/automations/health?user_id={guinea_id}"
                      ).status_code == 403


def test_the_targets_are_published_even_where_they_are_not_set(client, admin_id):
    """The section names performance targets; the numbers were not given to
    this build. Rather than inventing them, the endpoint says so — an empty
    target is a visible gap, a guessed one is a false pass."""
    t = _health(client, admin_id)["targets"]
    assert "source" in t and t["source"] in ("spec", "unset"), t
