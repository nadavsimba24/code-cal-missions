"""סעיף 17.2 — שירותי ה-API: מה קיים, ומה כל פעולת שינוי מחויבת בו.

The endpoints themselves were built section by section and the inventory is
nearly complete. What was missing is the thing a table of services says last
and matters most, because it applies to every row of it:

    "כל פעולת שינוי תחייב הרשאה, בדיקת גרסה למניעת דריסה ותיעוד Audit"

Permission was there. Audit arrived with section 13. The version check was
not there at all — two people with the same rule open both saved, and the
second one won without either of them being told. That is the quietest way
to lose work in the product: nothing fails, nothing is logged as a conflict,
and the first person's change is simply not there any more.
"""
import inspect

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AuditLog

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _add(client, bid, admin_id, recipe_id="created_set_priority", config=None, **extra):
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": recipe_id,
                          "config": config or {"a_priority": "high"}, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _routes():
    return {(r.path, m) for r in cityos_main.app.routes
            for m in getattr(r, "methods", set()) if "automation" in r.path}


# ── כל שורה בטבלה ──────────────────────────────────────────────────────────

def test_every_capability_group_has_its_service():
    want = [
        # ניהול אוטומציות
        ("/api/boards/{board_id}/automations", "GET"),
        ("/api/boards/{board_id}/automations", "POST"),
        ("/api/automations/{automation_id}", "PATCH"),
        ("/api/automations/{automation_id}", "DELETE"),
        # גרסאות
        ("/api/automations/{automation_id}/versions", "GET"),
        ("/api/automations/{automation_id}/versions/compare", "GET"),
        ("/api/automations/{automation_id}/restore/{version}", "POST"),
        ("/api/automations/{automation_id}/publish", "POST"),
        ("/api/automations/{automation_id}/discard-draft", "POST"),
        # שכפול
        ("/api/automations/{automation_id}/duplicate", "POST"),
        # Validate · Dry Run · הפעלה ידנית
        ("/api/boards/{board_id}/automations/validate", "POST"),
        ("/api/automations/{automation_id}/test", "POST"),
        ("/api/boards/{board_id}/automations/tests", "GET"),
        ("/api/automations/{automation_id}/run", "POST"),
        ("/api/automations/{automation_id}/impact", "GET"),
        # פעולות מרובות · סדר
        ("/api/boards/{board_id}/automations/bulk", "POST"),
        ("/api/boards/{board_id}/automations/order", "GET"),
        ("/api/boards/{board_id}/automations/order", "POST"),
        # לוגים · Retry · כשלים
        ("/api/boards/{board_id}/automations/runs", "GET"),
        ("/api/boards/{board_id}/automations/runs/export", "GET"),
        ("/api/automation-runs/{run_id}/timeline", "GET"),
        ("/api/automation-runs/{run_id}/retry-plan", "GET"),
        ("/api/automation-runs/{run_id}/retry", "POST"),
        ("/api/boards/{board_id}/automations/incidents", "GET"),
        ("/api/automation-incidents/{incident_id}", "PATCH"),
        ("/api/automation-queue/{queue_id}/cancel", "POST"),
        ("/api/boards/{board_id}/automations/queue", "GET"),
        ("/api/boards/{board_id}/automations/audit", "GET"),
        # יכולות ותלויות לפי לוח
        ("/api/automation-capabilities", "GET"),
        ("/api/boards/{board_id}/automations/dependents", "GET"),
        ("/api/boards/{board_id}/automations/templates", "GET"),
        ("/api/automations/recipes", "GET"),
        # ניהול ארגוני · השבתת חירום
        ("/api/admin/automations", "GET"),
        ("/api/admin/automations/export", "GET"),
        ("/api/admin/automations/health", "GET"),
        ("/api/admin/automations/freeze", "POST"),
        ("/api/admin/automations/release", "POST"),
    ]
    have = _routes()
    missing = [w for w in want if w not in have]
    assert missing == [], missing


# ── Validate ───────────────────────────────────────────────────────────────

def test_validate_says_a_good_rule_is_good_and_saves_nothing(client, admin_id):
    bid = _board(client, admin_id, "לוח אימות")
    before = len(client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                            ).json()["automations"])
    r = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "created_set_priority",
                          "config": {"a_priority": "high"}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["valid"] is True and d["errors"] == [] and d["missing_fields"] == []
    assert d["sentence"], d
    after = len(client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                           ).json()["automations"])
    assert after == before, "validate created something"


def test_validate_names_what_is_missing_without_refusing_the_call(client, admin_id):
    """A 400 on a half-built rule is what SAVE does. Validate is the thing
    somebody calls while typing, and it has to answer rather than throw."""
    bid = _board(client, admin_id, "לוח אימות חסר")
    r = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "status_set_priority", "config": {}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["valid"] is False
    assert d["missing_fields"], d


def test_validate_catches_what_only_the_board_knows(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח אימות לוח")
    r = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "status_assign_person",
                          "config": {"t_status": "done", "a_person": guinea_id}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["valid"] is False
    assert any("הוזמנו ללוח" in e or "חבר" in e or "הרשאה" in e
               for e in d["errors"]), d


def test_validate_warns_without_failing(client, admin_id):
    bid = _board(client, admin_id, "לוח אימות אזהרה")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "low"})
    r = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "created_set_priority",
                          "config": {"a_priority": "high"}})
    d = r.json()
    assert d["valid"] is True, d
    assert d["warnings"], "a second rule writing the same field was not mentioned"


def test_validate_is_for_somebody_who_could_save_it(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח אימות הרשאה")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    r = client.post(f"/api/boards/{bid}/automations/validate?user_id={guinea_id}",
                    json={"recipe_id": "created_set_priority",
                          "config": {"a_priority": "high"}})
    assert r.status_code == 403, r.text


def test_validate_checks_an_existing_rule_too(client, admin_id):
    bid = _board(client, admin_id, "לוח אימות קיים")
    a = _add(client, bid, admin_id)
    r = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"automation_id": a["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["valid"] is True, r.json()


# ── בדיקת גרסה למניעת דריסה ───────────────────────────────────────────────

def test_the_rule_hands_back_the_version_to_send_next_time(client, admin_id):
    bid = _board(client, admin_id, "לוח גרסה")
    a = _add(client, bid, admin_id)
    assert a.get("etag"), a
    row = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                     ).json()["automations"][0]
    assert row["etag"] == a["etag"]


def test_a_save_that_names_the_version_it_saw_goes_through(client, admin_id):
    bid = _board(client, admin_id, "לוח גרסה תקינה")
    a = _add(client, bid, admin_id)
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                     json={"name": "שם חדש", "expected_version": a["etag"]})
    assert r.status_code == 200, r.text
    assert r.json()["etag"] != a["etag"], "the token did not move with the change"


def test_a_save_against_a_version_somebody_else_moved_is_refused(client, admin_id,
                                                                 member_id):
    """The quietest way to lose work: both save, the second wins, neither is
    told. It is a 409 now, with what the rule says NOW so the client can show
    the difference rather than just the word "conflict"."""
    bid = _board(client, admin_id, "לוח התנגשות")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "admin"})
    a = _add(client, bid, admin_id, name="מקורי")
    stale = a["etag"]
    first = client.patch(f"/api/automations/{a['id']}?user_id={member_id}",
                         json={"name": "שינוי ראשון", "expected_version": stale})
    assert first.status_code == 200, first.text
    second = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                          json={"name": "שינוי שני", "expected_version": stale})
    assert second.status_code == 409, second.text
    body = second.json()["detail"]
    assert isinstance(body, dict) and body.get("current"), body
    assert body["current"]["name"] == "שינוי ראשון", body
    with Session(cityos_main.engine) as db:
        assert db.query(Automation).filter(
            Automation.id == a["id"]).first().name == "שינוי ראשון"


def test_a_save_that_names_no_version_still_works(client, admin_id):
    """Backward compatible on purpose: every existing caller sends nothing,
    and a check nobody can satisfy is a product that stops working on deploy."""
    bid = _board(client, admin_id, "לוח בלי גרסה")
    a = _add(client, bid, admin_id)
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                     json={"name": "ללא בדיקה"})
    assert r.status_code == 200, r.text


def test_the_other_writes_check_it_too(client, admin_id):
    bid = _board(client, admin_id, "לוח כל הכתיבות")
    a = _add(client, bid, admin_id)
    stale = a["etag"]
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"name": "זז"})
    for path, body in (
        (f"/api/automations/{a['id']}/publish", {"expected_version": stale}),
        (f"/api/automations/{a['id']}/discard-draft", {"expected_version": stale}),
        (f"/api/automations/{a['id']}/duplicate", {"expected_version": stale}),
    ):
        r = client.post(f"{path}?user_id={admin_id}", json=body)
        assert r.status_code == 409, (path, r.status_code, r.text[:120])
    r = client.delete(f"/api/automations/{a['id']}?user_id={admin_id}"
                      f"&expected_version={stale}")
    assert r.status_code == 409, r.text


def test_deleting_with_the_right_version_goes_through(client, admin_id):
    bid = _board(client, admin_id, "לוח מחיקה בגרסה")
    a = _add(client, bid, admin_id)
    r = client.delete(f"/api/automations/{a['id']}?user_id={admin_id}"
                      f"&expected_version={a['etag']}")
    assert r.status_code == 200, r.text


# ── הרשאה ו-Audit על כל פעולת שינוי ───────────────────────────────────────

MUTATING = [
    ("POST", "/api/boards/{board_id}/automations"),
    ("PATCH", "/api/automations/{automation_id}"),
    ("DELETE", "/api/automations/{automation_id}"),
    ("POST", "/api/automations/{automation_id}/duplicate"),
    ("POST", "/api/automations/{automation_id}/publish"),
    ("POST", "/api/automations/{automation_id}/discard-draft"),
    ("POST", "/api/automations/{automation_id}/restore/{version}"),
    ("POST", "/api/automations/{automation_id}/run"),
    ("POST", "/api/automation-runs/{run_id}/retry"),
    ("POST", "/api/boards/{board_id}/automations/bulk"),
    ("POST", "/api/boards/{board_id}/automations/order"),
    ("POST", "/api/automation-queue/{queue_id}/cancel"),
    ("PATCH", "/api/automation-incidents/{incident_id}"),
    ("POST", "/api/admin/automations/freeze"),
    ("POST", "/api/admin/automations/release"),
]


def test_every_mutating_service_checks_a_permission():
    """Read off the source: a route whose body never asks is a route that
    answers to whoever called it."""
    import re
    src = inspect.getsource(cityos_main)
    for method, path in MUTATING:
        i = src.index(f'@app.{method.lower()}("{path}")')
        body = src[i:src.index("\n@app.", i + 10)]
        assert ("_can_manage_automations" in body or "_require_sys_admin" in body
                or "_check_automation_act" in body or "_require_board_edit" in body
                or "_can_export_automations" in body), (method, path)


def test_every_mutating_service_leaves_an_audit_row():
    import re
    src = inspect.getsource(cityos_main)
    missing = []
    for method, path in MUTATING:
        i = src.index(f'@app.{method.lower()}("{path}")')
        body = src[i:src.index("\n@app.", i + 10)]
        if not ("_audit_automation" in body or "AuditLog(" in body
                or "_audit_owner_change" in body or "_queue_set_state" in body):
            missing.append(f"{method} {path}")
    assert missing == [], missing


def test_the_changes_really_land_in_the_audit(client, admin_id):
    bid = _board(client, admin_id, "לוח אודיט שירותים")
    a = _add(client, bid, admin_id, name="ראשונה")
    b2 = _add(client, bid, admin_id, "created_set_status",
              {"a_status": "done"}, name="שנייה")
    client.post(f"/api/automations/{a['id']}/duplicate?user_id={admin_id}", json={})
    r = client.post(f"/api/boards/{bid}/automations/order?user_id={admin_id}",
                    json={"ids": [b2["id"], a["id"]]})
    assert r.status_code == 200 and r.json()["moved"] >= 1, r.text
    rows = client.get(f"/api/boards/{bid}/automations/audit?user_id={admin_id}"
                      ).json()["audit"]
    acts = {r["action"] for r in rows}
    assert "create" in acts, acts
    assert "order" in acts or "update" in acts, acts
