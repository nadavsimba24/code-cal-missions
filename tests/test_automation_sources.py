"""Group — מקורות שינוי: which changes are the board's doing, and which are not.

  ממשק / עריכה מרובה / API · set the rules off, and the API hands back the id
                              of what it raised
  אוטומציה אחרת             · sets them off, under the loop guard and the depth
                              ceiling
  ייבוא                     · does not — and can be approved separately, after
                              being shown how many items, how many runs and how
                              much of the month's allowance is left
  מיגרציה / שחזור           · never
  תיקון מערכתי              · not unless marked in advance as a business event
  הפעלה ידנית               · does, and is logged as its own source
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AutomationQueue, AutomationRun, AutomationUsage, Task


STARTER_ITEMS = 3        # every new board opens with three, so a blank board is not blank


def _board(client, admin_id, name="לוח מקורות", bare=False):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    if bare:
        # the counts in this file are about the items a test put there
        with Session(cityos_main.engine) as db:
            db.query(Task).filter(Task.board_id == bid).delete()
            db.commit()
    return bid


def _member(client, admin_id, bid, uid, role="editor"):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    assert r.status_code == 200, r.text


def _add(client, bid, admin_id, recipe_id="created_set_priority", config=None, **extra):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id,
                          "config": config or {"a_priority": "high"}, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title="פריט", **extra):
    r = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                        "user_id": admin_id, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _runs(client, bid, admin_id, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}{qs}"
                      ).json()["runs"]


def _prio(tid):
    with Session(cityos_main.engine) as db:
        return cityos_main._task_priority_key(db.query(Task).filter(Task.id == tid).first())


# ── the sources that are the board doing something ─────────────────────────

def test_an_edit_through_the_api_fires_and_hands_back_the_event(client, admin_id):
    bid = _board(client, admin_id, "לוח ממשק")
    _add(client, bid, admin_id)
    made = _item(client, bid, admin_id)
    assert made["event_ids"], "the call did not say what it raised"
    assert _prio(made["id"]) == "high"
    # and the log can be asked about exactly that event
    runs = _runs(client, bid, admin_id, event_id=made["event_ids"][0])
    assert len(runs) == 1 and runs[0]["task_id"] == made["id"]
    assert runs[0]["event_id"] == made["event_ids"][0]


def test_an_edit_that_raises_several_events_says_so(client, admin_id):
    bid = _board(client, admin_id, "לוח כמה אירועים")
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    cols.append({"id": "col_txt", "type": "text", "title": "הערה"})
    client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    tid = _item(client, bid, admin_id)["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "status": "done",
                                                "custom_fields": {"col_txt": "משהו"}})
    assert r.status_code == 200, r.text
    ids = r.json()["event_ids"]
    assert len(ids) >= 2, ids
    assert len(set(ids)) == len(ids), "two events share an id"


def test_the_api_can_name_its_own_source(client, admin_id):
    bid = _board(client, admin_id, "לוח API")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)["id"]
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "status": "done",
                                            "source": "api"})
    runs = _runs(client, bid, admin_id)
    assert runs[0]["source"] == "api" and runs[0]["outcome"] == "ran"


def test_a_manual_run_is_its_own_source_and_is_logged(client, admin_id):
    bid = _board(client, admin_id, "לוח ידני")
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
             status="paused")
    tid = _item(client, bid, admin_id)["id"]
    r = client.post(f"/api/automations/{a['id']}/run?user_id={admin_id}",
                    json={"task_id": tid})
    assert r.status_code == 200, r.text
    assert r.json()["run"]["source"] == "manual"


def test_one_rule_setting_off_another_is_the_engines_own_source(client, admin_id):
    bid = _board(client, admin_id, "לוח שרשור")
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)["id"]
    assert _prio(tid) == "critical"
    cascaded = [r for r in _runs(client, bid, admin_id) if r["depth"] > 0]
    assert cascaded and {r["source"] for r in cascaded} == {"automation"}


def test_a_cascade_still_stops_at_the_depth_ceiling(client, admin_id):
    """The one qualification the table puts on an automation as a source."""
    bid = _board(client, admin_id, "לוח תקרה")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    _add(client, bid, admin_id, "priority_assign_person",
         {"t_priority": "critical", "a_person": admin_id})
    _add(client, bid, admin_id, "assigned_set_status", {"a_status": "in_progress"})
    _add(client, bid, admin_id, "status_notify_assignees", {"t_status": "in_progress"})
    tid = _item(client, bid, admin_id)["id"]
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    runs = _runs(client, bid, admin_id)
    assert any(r["depth"] >= cityos_main.AUTOMATION_MAX_DEPTH for r in runs)
    stopped = [r for r in runs if "עומק" in (r["reason"] or "")]
    assert stopped and stopped[0]["outcome"] == "skipped"


# ── the sources that are not ───────────────────────────────────────────────

def _silent(client, bid, admin_id, source, **extra):
    tid = _item(client, bid, admin_id)["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "status": "done",
                                                "source": source, **extra})
    assert r.status_code == 200, r.text
    return tid


def test_an_import_does_not_set_anything_off(client, admin_id):
    bid = _board(client, admin_id, "לוח ייבוא")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _silent(client, bid, admin_id, "import")
    assert _prio(tid) != "critical"
    assert _runs(client, bid, admin_id) == [], "an import wrote history it did not make"


def test_a_migration_never_does_even_if_it_asks(client, admin_id):
    """A board moved from monday, or restored from a backup, is the past being
    written down — and there is no flag that turns that into the present."""
    bid = _board(client, admin_id, "לוח מיגרציה")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    for extra in ({}, {"approved": True}, {"business": True}):
        tid = _silent(client, bid, admin_id, "migration", **extra)
        assert _prio(tid) != "critical", extra
    assert _runs(client, bid, admin_id) == []


def test_a_system_fix_is_silent_unless_it_was_marked(client, admin_id):
    bid = _board(client, admin_id, "לוח תיקון")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    quiet = _silent(client, bid, admin_id, "repair")
    assert _prio(quiet) != "critical"

    loud = _silent(client, bid, admin_id, "repair", business=True)
    assert _prio(loud) == "critical", "a fix marked as a business event stayed silent"
    runs = _runs(client, bid, admin_id)
    assert len(runs) == 1 and runs[0]["source"] == "repair"


def test_the_table_of_sources_is_the_one_in_the_spec(client):
    silent = set(cityos_main.AUTOMATION_SILENT_SOURCES)
    assert silent == {"import", "migration", "repair"}
    assert set(cityos_main.AUTOMATION_SILENT_OVERRIDE) == {"import", "repair"}
    for s in ("item", "create", "bulk", "api", "automation", "manual", "date", "link"):
        assert cityos_main._fires({"source": s}), s
    assert cityos_main._fires({}) is True          # nothing said: an ordinary change


# ── approving an import, after being shown what it comes to ────────────────

def test_the_preview_says_how_many_items_runs_and_quota(client, admin_id):
    bid = _board(client, admin_id, "לוח תצוגה מקדימה", bare=True)
    _add(client, bid, admin_id)                    # one created-rule
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    for i in range(4):
        _item(client, bid, admin_id, f"פריט {i}")
    d = client.get(f"/api/boards/{bid}/automations/import-preview?user_id={admin_id}").json()
    assert d["items"] == 4 and d["rules"] == 2
    assert d["estimated_runs"] == 8 and d["estimate_is_a_floor"] is True
    assert d["quota"]["limit"] == cityos_main.AUTOMATION_MONTHLY_QUOTA
    assert d["quota"]["left"] <= d["quota"]["limit"] and d["fits"] is True
    assert d["can_approve"] is True and d["pending"] == 0
    assert "ייבוא אינו מפעיל" in d["note"]


def _imported(client, bid, admin_id, n):
    """Items that arrived the way an import's do: already there, having set
    nothing off."""
    return [_item(client, bid, admin_id, f"פריט {i}", source="import")["id"]
            for i in range(n)]


def test_approving_queues_instead_of_firing(client, admin_id):
    """"האירועים יישלחו לתור ... ולא יחסמו" — approving answers at once, and
    nothing has run yet when it does."""
    bid = _board(client, admin_id, "לוח אישור", bare=True)
    _add(client, bid, admin_id)
    ids = _imported(client, bid, admin_id, 3)
    assert all(_prio(i) != "high" for i in ids), "the import fired on its own"
    r = client.post(f"/api/boards/{bid}/automations/import-run?user_id={admin_id}", json={})
    assert r.status_code == 200, r.text
    assert r.json()["queued"] == 3 and r.json()["batch_id"]
    with Session(cityos_main.engine) as db:
        assert db.query(AutomationQueue).filter(
            AutomationQueue.board_id == bid, AutomationQueue.done_at == None).count() == 3
    assert all(_prio(i) != "high" for i in ids), "approving fired instead of queueing"


def test_the_queue_goes_out_a_slice_at_a_time(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח קצב", bare=True)
    _add(client, bid, admin_id)
    ids = _imported(client, bid, admin_id, 5)
    monkeypatch.setattr(cityos_main, "AUTOMATION_QUEUE_SLICE", 2)
    client.post(f"/api/boards/{bid}/automations/import-run?user_id={admin_id}", json={})

    first = client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}").json()
    assert first["sent_now"] == 2 and first["pending"] == 3
    second = client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}").json()
    assert second["sent_now"] == 2 and second["pending"] == 1
    third = client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}").json()
    assert third["sent_now"] == 1 and third["pending"] == 0
    assert all(_prio(i) == "high" for i in ids), "the queue did not finish"
    runs = _runs(client, bid, admin_id)
    assert len(runs) == 5 and {r["source"] for r in runs} == {"import"}
    assert len({r["batch_id"] for r in runs}) == 1, "the approval was not one batch"


def test_a_queued_event_is_the_only_import_that_fires(client, admin_id):
    """The marker the approval puts on it is what lets it through — the same
    event without it is an import like any other."""
    assert cityos_main._fires({"source": "import"}) is False
    assert cityos_main._fires({"source": "import", "approved": True}) is True


def test_an_item_deleted_before_its_turn_is_skipped_not_crashed_on(client, admin_id):
    bid = _board(client, admin_id, "לוח פריט שנמחק", bare=True)
    _add(client, bid, admin_id)
    keep = _item(client, bid, admin_id, "נשאר", source="import")["id"]
    gone = _item(client, bid, admin_id, "נמחק", source="import")["id"]
    client.post(f"/api/boards/{bid}/automations/import-run?user_id={admin_id}", json={})
    client.delete(f"/api/tasks/{gone}?user_id={admin_id}")
    d = client.get(f"/api/boards/{bid}/automations/queue?user_id={admin_id}").json()
    assert d["pending"] == 0
    assert _prio(keep) == "high"
    assert [r["task_id"] for r in _runs(client, bid, admin_id)] == [keep]


# ── what approving refuses ─────────────────────────────────────────────────

def test_only_a_board_admin_may_approve(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח אישור הרשאות", bare=True)
    _member(client, admin_id, bid, guinea_id, "editor")
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    assert client.post(f"/api/boards/{bid}/automations/import-run?user_id={guinea_id}",
                       json={}).status_code == 403
    # and seeing the preview follows the viewing permission
    assert client.get(f"/api/boards/{bid}/automations/import-preview?user_id={guinea_id}"
                      ).status_code == 403


def test_a_board_with_no_matching_rule_has_nothing_to_approve(client, admin_id):
    bid = _board(client, admin_id, "לוח בלי כלל", bare=True)
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "high"})       # not a created-rule
    _item(client, bid, admin_id)
    r = client.post(f"/api/boards/{bid}/automations/import-run?user_id={admin_id}", json={})
    assert r.status_code == 400 and "יצירת פריט" in r.json()["detail"]


def test_approving_twice_is_refused_rather_than_doubled(client, admin_id):
    bid = _board(client, admin_id, "לוח אישור כפול", bare=True)
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    assert client.post(f"/api/boards/{bid}/automations/import-run?user_id={admin_id}",
                       json={}).status_code == 200
    r = client.post(f"/api/boards/{bid}/automations/import-run?user_id={admin_id}", json={})
    assert r.status_code == 400 and "תור ממתין" in r.json()["detail"]


def test_an_approval_over_the_month_s_quota_is_held_back(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח מכסה", bare=True)
    _add(client, bid, admin_id)
    for i in range(3):
        _item(client, bid, admin_id, f"פריט {i}")
    monkeypatch.setattr(cityos_main, "AUTOMATION_MONTHLY_QUOTA", 1)
    d = client.get(f"/api/boards/{bid}/automations/import-preview?user_id={admin_id}").json()
    assert d["fits"] is False
    r = client.post(f"/api/boards/{bid}/automations/import-run?user_id={admin_id}", json={})
    assert r.status_code == 400 and "מכסה" in r.json()["detail"]
    # and a manager who means it can say so
    assert client.post(f"/api/boards/{bid}/automations/import-run?user_id={admin_id}",
                       json={"over_quota": True}).status_code == 200


def test_an_emergency_stop_holds_an_approval_too(client, admin_id):
    bid = _board(client, admin_id, "לוח השבתה", bare=True)
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    f = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "board", "board_id": bid, "reason": "חקירה"}).json()
    try:
        r = client.post(f"/api/boards/{bid}/automations/import-run?user_id={admin_id}",
                        json={})
        assert r.status_code == 400 and "מושהות" in r.json()["detail"]
    finally:
        client.post(f"/api/admin/automations/release?user_id={admin_id}",
                    json={"freeze_id": f["freeze"]["id"]})


def test_a_board_that_is_not_there_is_a_404(client, admin_id):
    assert client.get(f"/api/boards/{10 ** 7}/automations/import-preview?user_id={admin_id}"
                      ).status_code == 404
    assert client.post(f"/api/boards/{10 ** 7}/automations/import-run?user_id={admin_id}",
                       json={}).status_code == 404
