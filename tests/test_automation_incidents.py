"""Group — טיפול והתראות: a failure that somebody owns, until it is fixed.

A notification is where the handling of a broken rule starts and, until now,
also where it ended. The rule stopped, the owner was told once, and after that
nothing in the system knew whether anybody had looked. A rule suspended on a
Thursday afternoon and a rule suspended and fixed in ten minutes read exactly
the same from outside.

So a failure opens an INCIDENT — one per rule per kind of failure — and it has
the three things a handover needs: somebody can say they are on it, they can
say what they found, and if nobody says anything it goes up. Four working
hours to the board's managers, a working day to the system administrator; and
"טופל" is not a button somebody can press to make the red go away, because it
asks for a successful run first.

Underneath: identical failures coalesce to one notice per half hour, every
handling change is written to the Audit, and the log is kept for a year.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import (Automation, AutomationIncident, AutomationRun, AuditLog,
                    Board, Notification, Task)

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


def _notes(client, uid):
    return client.get(f"/api/notifications?user_id={uid}&limit=100",
                      headers=AS(uid)).json()["notifications"]


def _incidents(client, bid, admin_id, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    r = client.get(f"/api/boards/{bid}/automations/incidents?user_id={admin_id}{qs}")
    assert r.status_code == 200, r.text
    return r.json()["incidents"]


def _blow_up(kind):
    def boom(*a, **kw):
        raise kind
    return boom


def _break_temp(client, bid, admin_id, monkeypatch, n=1):
    """A rule that keeps hitting something transient. Recorded every time;
    said out loud only once the retries are spent or it is suspended."""
    monkeypatch.setattr(cityos_main, "_apply_priority_key",
                        _blow_up(RuntimeError("database is locked")))
    for i in range(n):
        _item(client, bid, admin_id, f"פריט {i}")
    monkeypatch.undo()


def _break_perm(client, bid, admin_id, monkeypatch, n=1):
    """A rule refused on what the engine read — permanent, and told at once."""
    monkeypatch.setattr(cityos_main, "_apply_priority_key",
                        _blow_up(cityos_main._Refused("ערך לא חוקי")))
    for i in range(n):
        _item(client, bid, admin_id, f"קבוע {i}")
    monkeypatch.undo()


_break_it = _break_perm


def _age(bid, hours):
    """Push every open incident back in time."""
    with Session(cityos_main.engine) as db:
        back = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
        for inc in db.query(AutomationIncident).filter(
                AutomationIncident.board_id == bid).all():
            inc.opened_at = back
            inc.notified_at = back
        db.commit()


# ── כשל פותח אירוע ומודיע ─────────────────────────────────────────────────

def test_a_permanent_failure_tells_the_owner_at_once(client, admin_id):
    a, b = _board(client, admin_id, "מקור טיפול"), _board(client, admin_id, "יעד טיפול")
    cols = client.get(f"/api/boards/{a}").json()["columns"] + [
        {"type": "connect", "title": "קישור",
         "connect": {"board_ids": [b], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in client.get(f"/api/boards/{a}").json()["columns"]
             if x["type"] == "connect")
    _add(client, a, admin_id, "link_added_copy_to_linked",
         {"a_fields": ["priority"], "a_connect": c["id"], "a_on_missing": "fail"})
    tid = _item(client, a, admin_id, "מקור", priority="critical")
    before = len(_notes(client, admin_id))
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        cityos_main._run_automations(
            db, t, cityos_main._event("link_added", "item", col=c["id"], item_ids=[]),
            admin_id)
        db.commit()
    assert len(_notes(client, admin_id)) > before, "a permanent failure told nobody"
    inc = _incidents(client, a, admin_id)
    assert len(inc) == 1 and inc[0]["status"] == "open", inc


def test_running_out_of_retries_tells_the_owner(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח מיצוי")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    before = len(_notes(client, admin_id))
    _break_temp(client, bid, admin_id, monkeypatch)
    for _ in range(5):
        with Session(cityos_main.engine) as db:
            back = datetime.now(timezone.utc) - timedelta(minutes=1)
            from models import AutomationQueue
            for r in db.query(AutomationQueue).filter(
                    AutomationQueue.board_id == bid,
                    AutomationQueue.done_at == None).all():       # noqa: E711
                r.event = {**(r.event or {}), "after": back.isoformat()}
                r.resume_at = back.replace(tzinfo=None)
            db.commit()
        monkeypatch.setattr(cityos_main, "_apply_priority_key",
                            _blow_up(RuntimeError("database is locked")))
        client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}")
        monkeypatch.undo()
    assert len(_notes(client, admin_id)) > before
    inc = _incidents(client, bid, admin_id)
    assert inc and inc[0]["attempts_exhausted"] is True, inc


def test_an_automatic_suspension_opens_one_too(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח השהיה אירוע")
    rule = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _break_temp(client, bid, admin_id, monkeypatch, n=cityos_main.AUTOMATION_FAIL_CUTOFF + 1)
    with Session(cityos_main.engine) as db:
        assert db.query(Automation).filter(
            Automation.id == rule["id"]).first().status == "paused_error"
    inc = _incidents(client, bid, admin_id)
    assert inc and inc[0]["suspended"] is True, inc


# ── איחוד כשלים זהים ──────────────────────────────────────────────────────

def test_identical_failures_are_one_notice_per_half_hour(client, admin_id, monkeypatch):
    """Twenty items edited at once is twenty failures and one problem."""
    bid = _board(client, admin_id, "לוח איחוד")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    before = len([n for n in _notes(client, admin_id) if "אוטומציה" in (n.get("title") or "")])
    _break_perm(client, bid, admin_id, monkeypatch, n=4)
    after = len([n for n in _notes(client, admin_id) if "אוטומציה" in (n.get("title") or "")])
    assert after - before == 1, f"{after - before} notices for one problem"
    inc = _incidents(client, bid, admin_id)
    assert inc[0]["count"] >= 4, inc[0]


def test_the_window_is_half_an_hour(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח חלון")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _break_it(client, bid, admin_id, monkeypatch)
    n1 = len(_notes(client, admin_id))
    _break_it(client, bid, admin_id, monkeypatch)
    assert len(_notes(client, admin_id)) == n1, "it told them twice inside the window"
    _age(bid, hours=1)
    _break_it(client, bid, admin_id, monkeypatch)
    assert len(_notes(client, admin_id)) > n1, "it never told them again"
    assert cityos_main.AUTOMATION_NOTICE_WINDOW_MIN == 30


def test_a_different_failure_is_a_different_incident(client, admin_id, monkeypatch):
    """Coalescing is per KIND. Two different things going wrong with one rule
    is two problems, and folding them together loses the second."""
    bid = _board(client, admin_id, "לוח שני סוגים")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _break_it(client, bid, admin_id, monkeypatch)

    monkeypatch.setattr(cityos_main, "_apply_priority_key",
                        _blow_up(ValueError("ערך לא חוקי")))
    _item(client, bid, admin_id, "אחר")
    monkeypatch.undo()
    kinds = {i["error_code"] for i in _incidents(client, bid, admin_id)}
    assert kinds == {"refused", "ValueError"}, kinds


# ── בטיפול, טופל, הערה ────────────────────────────────────────────────────

def _one(client, bid, admin_id):
    return _incidents(client, bid, admin_id)[0]


def test_the_owner_can_say_they_are_on_it(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח בטיפול")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _break_it(client, bid, admin_id, monkeypatch)
    inc = _one(client, bid, admin_id)
    r = client.patch(f"/api/automation-incidents/{inc['id']}?user_id={admin_id}",
                     json={"status": "acknowledged", "note": "בודקת מול התשתית"})
    assert r.status_code == 200, r.text
    got = _one(client, bid, admin_id)
    assert got["status"] == "acknowledged"
    assert got["note"] == "בודקת מול התשתית"
    assert got["acked_by"] == admin_id and got["acked_at"]


def test_a_fix_cannot_be_closed_before_something_works(client, admin_id, monkeypatch):
    """«תיקון ייסגר רק לאחר הפעלה מוצלחת אחת לפחות» — otherwise "טופל" is a
    button for making the red go away."""
    bid = _board(client, admin_id, "לוח סגירה")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _break_it(client, bid, admin_id, monkeypatch)
    inc = _one(client, bid, admin_id)
    r = client.patch(f"/api/automation-incidents/{inc['id']}?user_id={admin_id}",
                     json={"status": "resolved"})
    assert r.status_code == 400, r.text
    assert "מוצלחת" in r.json()["detail"], r.json()


def test_and_can_be_closed_once_something_does(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח סגירה תקינה")
    rule = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _break_it(client, bid, admin_id, monkeypatch)
    with Session(cityos_main.engine) as db:         # put it back in service
        a = db.query(Automation).filter(Automation.id == rule["id"]).first()
        cityos_main._set_automation_status(a, "active")
        a.consecutive_failures = 0
        db.commit()
    _item(client, bid, admin_id, "עובד")            # a run that works
    inc = _one(client, bid, admin_id)
    r = client.patch(f"/api/automation-incidents/{inc['id']}?user_id={admin_id}",
                     json={"status": "resolved", "note": "התשתית חזרה"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"
    # and it leaves the list of things to deal with, which is the point
    assert _incidents(client, bid, admin_id) == []
    kept = _incidents(client, bid, admin_id, include_resolved="true")
    assert kept and kept[0]["status"] == "resolved" and kept[0]["note"] == "התשתית חזרה"


def test_every_change_of_handling_is_written_down(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח תיעוד טיפול")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _break_it(client, bid, admin_id, monkeypatch)
    inc = _one(client, bid, admin_id)
    client.patch(f"/api/automation-incidents/{inc['id']}?user_id={admin_id}",
                 json={"status": "acknowledged", "note": "ראשונה"})
    client.patch(f"/api/automation-incidents/{inc['id']}?user_id={admin_id}",
                 json={"note": "שנייה"})
    with Session(cityos_main.engine) as db:
        rows = db.query(AuditLog).filter(AuditLog.entity_type == "automation_incident",
                                         AuditLog.entity_id == inc["id"]).all()
    assert len(rows) >= 2, [(r.action, r.field_name, r.new_value) for r in rows]
    assert any("שנייה" in (r.new_value or "") for r in rows), rows


def test_somebody_who_may_not_manage_the_board_cannot_touch_it(client, admin_id,
                                                               guinea_id, monkeypatch):
    bid = _board(client, admin_id, "לוח טיפול סגור")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _break_it(client, bid, admin_id, monkeypatch)
    inc = _one(client, bid, admin_id)
    assert client.patch(f"/api/automation-incidents/{inc['id']}?user_id={guinea_id}",
                        json={"status": "acknowledged"}).status_code == 403
    assert client.get(f"/api/boards/{bid}/automations/incidents?user_id={guinea_id}"
                      ).status_code == 403


# ── הסלמה בשעות עבודה ─────────────────────────────────────────────────────

def test_four_working_hours_reach_the_board_managers(client, admin_id, member_id,
                                                     monkeypatch):
    """Four working hours and not nine: the board's rung, not the system's.

    The window is pinned open for the length of this case so that aged hours
    ARE working hours. It used to age by three calendar days and trust that
    to land between the two rungs — and three days is four working hours on a
    Friday and thirteen on a Monday, so the case passed or failed by the day
    of the week it was run on. The ladder is what is being tested here; which
    hours count is tested by test_the_clock_only_runs_in_working_hours, where
    the window is the real one and the point.

    Five hours, because the sweep runs more than once: reading the incident
    list is what sweeps, and this case reads it twice. The first pass puts an
    unescalated incident on the board rung; a second pass promotes anything
    already there once it passes WORK_HOURS_PER_DAY. Five is past four and
    short of nine, so the second read finds nothing left to do.
    """
    monkeypatch.setattr(cityos_main, "WORK_DAYS", (0, 1, 2, 3, 4, 5, 6))
    monkeypatch.setattr(cityos_main, "WORK_START_HOUR", 0)
    monkeypatch.setattr(cityos_main, "WORK_END_HOUR", 24)
    assert 4 < 5 < cityos_main.WORK_HOURS_PER_DAY, "the two rungs moved"

    bid = _board(client, admin_id, "לוח הסלמה")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "admin"})
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"},
         owner_id=admin_id)
    _break_it(client, bid, admin_id, monkeypatch)
    before = len(_notes(client, member_id))
    _age(bid, hours=5)                       # five working hours, on any day
    _incidents(client, bid, admin_id)        # reading the list is what sweeps
    after = _notes(client, member_id)
    assert len(after) > before, "nobody was escalated to"
    assert any("הסלמה" in (n.get("title") or "") for n in after[:3]), after[:2]
    assert _one(client, bid, admin_id)["escalated"] == "board"


def test_an_acknowledged_incident_is_not_escalated(client, admin_id, member_id,
                                                   monkeypatch):
    """The whole point of the button: saying you are on it stops the chasing."""
    bid = _board(client, admin_id, "לוח ללא הסלמה")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "admin"})
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _break_it(client, bid, admin_id, monkeypatch)
    inc = _one(client, bid, admin_id)
    client.patch(f"/api/automation-incidents/{inc['id']}?user_id={admin_id}",
                 json={"status": "acknowledged"})
    before = len(_notes(client, member_id))
    _age(bid, hours=24 * 7)
    _incidents(client, bid, admin_id)
    assert len(_notes(client, member_id)) == before, "it chased an incident somebody owns"


def test_a_working_day_reaches_the_system_administrator(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח הסלמה מנהל")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _break_it(client, bid, admin_id, monkeypatch)
    _age(bid, hours=24 * 14)
    _incidents(client, bid, admin_id)
    assert _one(client, bid, admin_id)["escalated"] == "system"


def test_the_clock_only_runs_in_working_hours(client, admin_id):
    """«ארבע שעות עבודה» — a rule that broke at five on Thursday has not had
    four working hours by nine on Friday morning."""
    tz = "Asia/Jerusalem"
    thu_evening = datetime(2026, 10, 22, 17, 0, tzinfo=timezone.utc)   # Thursday
    fri_morning = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)    # Friday
    sun_midday = datetime(2026, 10, 25, 13, 0, tzinfo=timezone.utc)    # Sunday
    assert cityos_main._working_hours(thu_evening, fri_morning, tz) < 4
    assert cityos_main._working_hours(thu_evening, sun_midday, tz) >= 4
    # Friday and Saturday count for nothing at all
    sat = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    assert cityos_main._working_hours(fri_morning, sat, tz) == 0


def test_the_working_day_is_published(client, admin_id):
    d = client.get(f"/api/automation-capabilities?user_id={admin_id}").json()
    assert d["handling"]["escalate_board_hours"] == 4
    assert d["handling"]["notice_window_minutes"] == 30
    assert d["handling"]["work_hours_per_day"] == cityos_main.WORK_HOURS_PER_DAY


# ── שמירה וייצוא ──────────────────────────────────────────────────────────

def test_the_retention_is_twelve_months_and_seven_years(client, admin_id):
    assert cityos_main.AUTOMATION_RUN_RETENTION_DAYS == 365
    assert cityos_main.AUDIT_RETENTION_DAYS == 365 * 7


def test_a_run_older_than_the_window_is_dropped(client, admin_id):
    bid = _board(client, admin_id, "לוח שמירה")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        old = (datetime.now(timezone.utc).replace(tzinfo=None)
               - timedelta(days=cityos_main.AUTOMATION_RUN_RETENTION_DAYS + 5))
        for r in db.query(AutomationRun).filter(AutomationRun.board_id == bid).all():
            r.created_at = old
        db.commit()
    _item(client, bid, admin_id, "חדש")          # one row inside the window
    client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}")
    with Session(cityos_main.engine) as db:
        left = db.query(AutomationRun).filter(AutomationRun.board_id == bid).all()
    assert len(left) == 1, [(r.id, r.created_at) for r in left]


def test_an_organisation_may_keep_them_for_less(client, admin_id):
    """«בכפוף למדיניות הארגון» — the default is twelve months, not the law."""
    r = client.patch(f"/api/organization/settings?user_id={admin_id}",
                     json={"retention": {"automation_runs_days": 30}})
    assert r.status_code == 200, r.text
    assert r.json()["retention"]["automation_runs_days"] == 30
    client.patch(f"/api/organization/settings?user_id={admin_id}",
                 json={"retention": {"automation_runs_days": 365}})


def test_the_export_carries_everything_the_spec_lists(client, admin_id):
    bid = _board(client, admin_id, "לוח ייצוא מלא")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    r = client.get(f"/api/boards/{bid}/automations/runs/export?user_id={admin_id}")
    assert r.status_code == 200, r.text
    head = r.text.splitlines()[0]
    for want in ("מזהה הפעלה", "האוטומציה", "לוח", "הפריט", "נקלט", "התחיל",
                 "הסתיים", "סטטוס", "ניסיון", "קוד שגיאה"):
        assert want in head, (want, head)


def _grant(cap, allowed, role):
    from models import RolePermission
    with Session(cityos_main.engine) as db:
        row = (db.query(RolePermission)
                 .filter(RolePermission.role == role,
                         RolePermission.capability == cap).first())
        if not row:
            row = RolePermission(role=role, capability=cap, allowed=allowed)
            db.add(row)
        row.allowed = allowed
        db.commit()


def _ws_role_of(uid):
    from models import User
    with Session(cityos_main.engine) as db:
        return (db.query(User.role).filter(User.id == uid).scalar() or "guest")


def test_the_business_values_follow_the_exporters_permission(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח ייצוא מוגן")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    _grant("export_automation_log", True, _ws_role_of(guinea_id))
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id, "חסוי")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        t.permissions = {**(t.permissions or {}), str(guinea_id): "none"}
        db.commit()
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    mine = client.get(f"/api/boards/{bid}/automations/runs/export?user_id={admin_id}").text
    assert "חסוי" in mine
    theirs = client.get(f"/api/boards/{bid}/automations/runs/export?user_id={guinea_id}")
    assert theirs.status_code == 200, theirs.text
    assert "חסוי" not in theirs.text, "a protected item's title left in an export"
    assert "todo ← done" in mine, "the values never reached the permitted export"
    assert "todo ← done" not in theirs.text, "a protected item's values left in an export"
    _grant("export_automation_log", False, _ws_role_of(guinea_id))


def test_the_export_itself_is_written_to_the_audit(client, admin_id):
    """«הפעולה תתועד ב־Audit» — a file leaving the system is an event."""
    bid = _board(client, admin_id, "לוח ייצוא מתועד")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    client.get(f"/api/boards/{bid}/automations/runs/export?user_id={admin_id}")
    with Session(cityos_main.engine) as db:
        rows = db.query(AuditLog).filter(AuditLog.entity_type == "automation_export",
                                         AuditLog.entity_id == bid).all()
    assert rows, "the export left no trace"
    assert rows[-1].changed_by == admin_id
    assert "שורות" in (rows[-1].new_value or ""), rows[-1].new_value


def test_the_export_is_still_closed_to_somebody_without_the_right(client, admin_id,
                                                                  member_id):
    bid = _board(client, admin_id, "לוח ייצוא סגור")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    assert client.get(f"/api/boards/{bid}/automations/runs/export?user_id={member_id}"
                      ).status_code == 403
