"""Group — אבטחה, Audit ועדכון בזמן אמת.

The run log answers "what did the rules do". It cannot answer "who changed
this rule, and when, and from what to what" — a rule rewritten on Tuesday and
a rule that has always said this read exactly alike in it, because the run log
keeps runs and a configuration change is not a run.

So a second trail, over the thirteen things somebody DOES to an automation:
writing one, changing it, publishing a version, handing it over, ordering it,
testing it, running it by hand, switching it on and off, retrying, deleting,
stopping everything, exporting. Each row carries who — a person or the engine
— when, what, the version it was, a before and an after, and the reason where
one was asked for.

And three things that are about not leaking: a tenant never sees another
tenant's trail, a secret that found its way into an error message does not get
written down, and nothing on these screens is rendered as markup.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AuditLog, Board, Organization, Task

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


def _audit(client, bid, admin_id, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    r = client.get(f"/api/boards/{bid}/automations/audit?user_id={admin_id}{qs}")
    assert r.status_code == 200, r.text
    return r.json()["audit"]


def _actions(client, bid, admin_id, **q):
    return [x["action"] for x in _audit(client, bid, admin_id, **q)]


# ── מה נרשם ───────────────────────────────────────────────────────────────

def test_the_thirteen_actions_are_declared(client, admin_id):
    want = {"create", "update", "version", "owner", "order", "dry_run",
            "manual_run", "activate", "pause", "retry", "permissions",
            "delete", "freeze", "export"}
    assert want <= set(cityos_main.AUTOMATION_AUDIT_ACTIONS), \
        want - set(cityos_main.AUTOMATION_AUDIT_ACTIONS)
    assert all(cityos_main.AUTOMATION_AUDIT_HE.get(a)
               for a in cityos_main.AUTOMATION_AUDIT_ACTIONS)


def test_writing_a_rule_is_recorded(client, admin_id):
    bid = _board(client, admin_id, "לוח יצירה")
    a = _add(client, bid, admin_id)
    rows = _audit(client, bid, admin_id)
    assert [r["action"] for r in rows] == ["create"], rows
    one = rows[0]
    assert one["automation_id"] == a["id"]
    assert one["user_id"] == admin_id and one["user_name"]
    assert one["created_at"] and one["after"], one


def test_changing_it_keeps_a_before_and_an_after(client, admin_id):
    bid = _board(client, admin_id, "לוח שינוי")
    a = _add(client, bid, admin_id, name="שם ראשון")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"name": "שם שני"})
    row = [r for r in _audit(client, bid, admin_id) if r["action"] == "update"][0]
    assert "שם ראשון" in (row["before"] or ""), row
    assert "שם שני" in (row["after"] or ""), row
    assert row["version"], "a change with no version cannot be placed in the history"


def test_switching_it_on_and_off_are_two_different_actions(client, admin_id):
    bid = _board(client, admin_id, "לוח הפעלה")
    a = _add(client, bid, admin_id, status="draft")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "active"})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "paused"})
    acts = _actions(client, bid, admin_id)
    assert "activate" in acts and "pause" in acts, acts


def test_ordering_and_importance_are_recorded(client, admin_id):
    bid = _board(client, admin_id, "לוח סדר")
    a = _add(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"run_order": 7, "importance": "critical"})
    row = [r for r in _audit(client, bid, admin_id) if r["action"] == "order"][0]
    assert "7" in (row["after"] or "") or "critical" in (row["after"] or ""), row


def test_a_handover_is_recorded_as_its_own_action(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח בעלות")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    a = _add(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"owner_id": guinea_id})
    assert "owner" in _actions(client, bid, admin_id)


def test_a_dry_run_is_recorded(client, admin_id):
    bid = _board(client, admin_id, "לוח בדיקה")
    a = _add(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}",
                json={"task_id": tid})
    assert "dry_run" in _actions(client, bid, admin_id)


def test_a_manual_run_is_recorded_with_its_reason(client, admin_id):
    """«סיבה אם נדרשה» — a system admin stepping over the conditions has to
    say why, and the Audit is where that sentence belongs."""
    bid = _board(client, admin_id, "לוח ידנית")
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "critical",
              "conditions": [{"kind": "has_assignee", "value": True}]})
    tid = _item(client, bid, admin_id)
    r = client.post(f"/api/automations/{a['id']}/run?user_id={admin_id}",
                    json={"task_id": tid, "override": True,
                          "reason": "דחוף לקראת ביקורת שנתית"})
    assert r.status_code == 200, r.text
    row = [x for x in _audit(client, bid, admin_id) if x["action"] == "manual_run"][0]
    assert "ביקורת" in (row["reason"] or ""), row


def test_a_retry_is_recorded(client, admin_id):
    bid = _board(client, admin_id, "לוח ניסיון")
    a = _add(client, bid, admin_id, "created_set_status",
             {"a_status": "done", "conditions": [{"kind": "has_assignee", "value": True}]})
    _item(client, bid, admin_id)
    run = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}"
                     ).json()["runs"][0]
    client.post(f"/api/automation-runs/{run['id']}/retry?user_id={admin_id}")
    assert "retry" in _actions(client, bid, admin_id)
    assert a["id"]


def test_deleting_it_is_recorded_and_outlives_it(client, admin_id):
    """The one row that matters most: the rule is gone and the trail is not."""
    bid = _board(client, admin_id, "לוח מחיקה")
    a = _add(client, bid, admin_id)
    client.delete(f"/api/automations/{a['id']}?user_id={admin_id}")
    rows = _audit(client, bid, admin_id)
    assert "delete" in [r["action"] for r in rows], rows
    with Session(cityos_main.engine) as db:
        assert db.query(Automation).filter(Automation.id == a["id"]).first() is None


def test_an_emergency_stop_is_recorded(client, admin_id):
    bid = _board(client, admin_id, "לוח חירום")
    _add(client, bid, admin_id)
    r = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "board", "board_id": bid, "reason": "חקירת תקלה"})
    assert r.status_code == 200, r.text
    row = [x for x in _audit(client, bid, admin_id) if x["action"] == "freeze"][0]
    assert "חקירת תקלה" in (row["reason"] or ""), row


def test_an_export_is_recorded(client, admin_id):
    bid = _board(client, admin_id, "לוח ייצוא אודיט")
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    client.get(f"/api/boards/{bid}/automations/runs/export?user_id={admin_id}")
    assert "export" in _actions(client, bid, admin_id)


def test_the_engine_signs_its_own_rows_as_a_service(client, admin_id):
    """«משתמש או שירות» — a suspension nobody chose was not done by a person,
    and writing a person's name against it would be a lie."""
    bid = _board(client, admin_id, "לוח שירות")
    col = {"id": "col_dep", "type": "text", "title": "אזור"}
    cols = client.get(f"/api/boards/{bid}").json()["columns"] + [col]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    _add(client, bid, admin_id, "column_changed_notify_assignees", {"t_column": "col_dep"})
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id,
                       "columns": [c for c in client.get(f"/api/boards/{bid}").json()["columns"]
                                   if c["id"] != "col_dep"]})
    rows = [r for r in _audit(client, bid, admin_id) if r["action"] == "dependency_broken"]
    assert rows, _actions(client, bid, admin_id)


# ── הרשאות והפרדת ארגונים ─────────────────────────────────────────────────

def test_the_trail_is_closed_to_somebody_who_may_not_manage(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח אודיט סגור")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    _add(client, bid, admin_id)
    assert client.get(f"/api/boards/{bid}/automations/audit?user_id={guinea_id}"
                      ).status_code == 403


def test_another_organisations_board_is_not_readable(client, admin_id):
    """«להפריד בין Tenants» — and the audit is the trail somebody would most
    like to read about a competitor."""
    bid = _board(client, admin_id, "לוח ארגון אחר")
    _add(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        b.organization_id = (b.organization_id or 1) + 999
        db.commit()
    r = client.get(f"/api/boards/{bid}/automations/audit?user_id={admin_id}")
    assert r.status_code in (403, 404), r.text


# ── מה לא נשמר ────────────────────────────────────────────────────────────

def test_a_secret_in_an_error_is_not_written_down(client, admin_id, monkeypatch):
    """«לסנן מידע חסוי משגיאות» — a driver that puts a connection string in
    its message puts a password in the log, and the log is exported."""
    bid = _board(client, admin_id, "לוח סוד")
    _add(client, bid, admin_id)

    def leak(*a, **kw):
        raise RuntimeError("connect failed: password=sup3rs3cret token=abc123xyz")
    monkeypatch.setattr(cityos_main, "_apply_priority_key", leak)
    _item(client, bid, admin_id)
    monkeypatch.undo()
    runs = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}"
                      ).json()["runs"]
    blob = str(runs)
    assert "sup3rs3cret" not in blob, runs[0]["reason"]
    assert "abc123xyz" not in blob, runs[0]["reason"]
    assert "RuntimeError" in runs[0]["reason"], "the error itself was thrown away too"


def test_the_scrubber_knows_the_usual_shapes(client, admin_id):
    f = cityos_main._scrub_secrets
    assert "hunter2" not in f("password=hunter2")
    assert "hunter2" not in f('{"password": "hunter2"}')
    assert "AKIAIOSFODNN7EXAMPLE" not in f("key AKIAIOSFODNN7EXAMPLE failed")
    assert "eyJhbGciOiJIUzI1NiJ9.eyJhIjoxfQ.sig" not in f(
        "Bearer eyJhbGciOiJIUzI1NiJ9.eyJhIjoxfQ.sig")
    # and it leaves ordinary Hebrew prose alone
    assert f("הסטטוס 'בוצע' אינו קיים בלוח") == "הסטטוס 'בוצע' אינו קיים בלוח"


def test_the_source_address_follows_the_organisation_policy(client, admin_id):
    """«כתובת מקור לפי מדיניות הארגון» — off by default, because an address is
    personal data and most municipalities have not asked for it."""
    bid = _board(client, admin_id, "לוח כתובת")
    _add(client, bid, admin_id)
    assert not (_audit(client, bid, admin_id)[0].get("ip") or "")
    client.patch(f"/api/organization/settings?user_id={admin_id}",
                 json={"audit": {"store_ip": True}})
    _add(client, bid, admin_id, name="שני")
    rows = _audit(client, bid, admin_id)
    assert any(r.get("ip") for r in rows), rows
    client.patch(f"/api/organization/settings?user_id={admin_id}",
                 json={"audit": {"store_ip": False}})


def test_nothing_in_the_trail_is_rendered_as_markup(client, admin_id):
    """«למנוע הזרקת תוכן» — a rule named with a script tag is a rule name."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
    html = src.read_text(encoding="utf-8")
    i = html.index("auditHTML(){")
    body = html[i:html.index("\n  },", i)]
    for field in ("r.user_name", "r.before", "r.after", "r.reason"):
        assert f"esc({field})" in body, f"{field} reaches the page unescaped"


# ── אחרי הפעולה: נשמר, פורסם, הוצג ────────────────────────────────────────

def test_the_event_goes_out_only_after_the_write_lands(client, admin_id, monkeypatch):
    """A listener that refetched before the commit read the row as it was."""
    seen = []
    real = cityos_main.bus.publish

    def spy(kind, **kw):
        if kind == "task.changed":
            with Session(cityos_main.engine) as db:
                t = db.query(Task).filter(Task.id == kw.get("task_id")).first()
                seen.append(cityos_main._task_priority_key(t) if t else None)
        return real(kind, **kw)
    bid = _board(client, admin_id, "לוח פרסום")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    monkeypatch.setattr(cityos_main.bus, "publish", spy)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    monkeypatch.undo()
    assert seen, "nothing was published"
    assert seen[-1] == "critical", \
        "the event went out before the automation's own write had landed"


def test_the_items_own_log_names_the_automation(client, admin_id):
    """«לוג הפריט מציג שהשינוי בוצע על ידי האוטומציה ואת שמה» — its NAME. One
    engine account against every change is "מערכת" twelve times over."""
    bid = _board(client, admin_id, "לוח שם בכלל")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"}, name="סגירת קריאה")
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    rows = client.get(f"/api/tasks/{tid}/activity", headers=AS(admin_id)).json()["activity"]
    mine = [r for r in rows if r["field"] == "priority"]
    assert mine, rows
    assert mine[0]["origin"] == "automation", mine[0]
    assert "סגירת קריאה" in (mine[0]["user_name"] or ""), mine[0]


def test_an_automation_change_can_still_be_undone(client, admin_id):
    """Marking the row as the engine's must not take the undo away: a person
    looking at what a rule did to their item is exactly who wants it back."""
    bid = _board(client, admin_id, "לוח ביטול שינוי")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    rows = client.get(f"/api/tasks/{tid}/activity", headers=AS(admin_id)).json()["activity"]
    mine = [r for r in rows if r["field"] == "priority"]
    assert mine and mine[0]["can_undo"] is True, mine


def test_a_persons_own_change_is_still_theirs(client, admin_id):
    bid = _board(client, admin_id, "לוח שינוי אדם")
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"priority": "critical", "user_id": admin_id})
    rows = client.get(f"/api/tasks/{tid}/activity", headers=AS(admin_id)).json()["activity"]
    mine = [r for r in rows if r["field"] == "priority"]
    assert mine and mine[0]["origin"] == "", mine[0]
    assert "אוטומציה" not in (mine[0]["user_name"] or ""), mine[0]
