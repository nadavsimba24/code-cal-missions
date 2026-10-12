"""Group — the impact preview before activation, and the Dry Run on one item.

Before switching a rule on, the screen has to show the boards and fields it
reads or updates, its connect/mirror dependencies, who it will notify, and which
other automations write the same fields.

"בדיקה על פריט" is a Dry Run: the trigger match, the result of each condition,
the actions with their expected values, missing permissions and a conflict or
loop warning. It changes nothing, sends nothing, and is kept 30 days in a log
of its own.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AutomationRun, AutomationTestRun, Notification, Task


def _board(client, admin_id, name="לוח בדיקות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _member(client, admin_id, bid, uid, role="editor"):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    assert r.status_code == 200, r.text


def _add(client, bid, admin_id, recipe_id="created_set_priority", config=None, **extra):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id, "config": config or {"a_priority": "high"},
                          **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _impact(client, aid, admin_id):
    r = client.get(f"/api/automations/{aid}/impact?user_id={admin_id}")
    assert r.status_code == 200, r.text
    return r.json()


def _dry(client, aid, tid, admin_id):
    r = client.post(f"/api/automations/{aid}/test?user_id={admin_id}", json={"task_id": tid})
    assert r.status_code == 200, r.text
    return r.json()


def _connect_board(client, admin_id, name, targets, two_way=False):
    bid = _board(client, admin_id, name)
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    cols.append({"id": "col_link", "type": "connect", "title": "קישור",
                 "connect": {"board_ids": targets, "multi": True, "two_way": two_way}})
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    assert r.status_code == 200, r.text
    return bid


# ── the impact preview ──────────────────────────────────────────────────────

def test_the_preview_names_the_board_and_the_fields(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "critical"})
    d = _impact(client, a["id"], admin_id)
    assert [x["id"] for x in d["boards"]] == [bid]
    assert d["boards"][0]["mode"] == "read_write"
    assert "סטטוס" in d["reads"], d["reads"]
    assert "עדיפות" in d["writes"], d["writes"]


def test_the_preview_names_the_other_board_a_rule_writes_on(client, admin_id):
    far = _board(client, admin_id, "לוח היעד")
    near = _connect_board(client, admin_id, "לוח המקור", [far])
    a = _add(client, near, admin_id, "created_create_and_link",
             {"a_connect": "col_link", "a_board": far, "a_text": "פריט חדש"})
    d = _impact(client, a["id"], admin_id)
    ids = {x["id"]: x for x in d["boards"]}
    assert far in ids and ids[far]["mode"] == "write"
    assert "יוצרת בו פריטים" in ids[far]["why"] or "מפנה אליו" in ids[far]["why"]


def test_the_preview_names_the_connect_dependency(client, admin_id):
    far = _board(client, admin_id, "יעד")
    near = _connect_board(client, admin_id, "מקור", [far], two_way=True)
    a = _add(client, near, admin_id, "created_link_item",
             {"a_connect": "col_link", "a_item": _item(client, far, admin_id, "שם")})
    d = _impact(client, a["id"], admin_id)
    conn = [l for l in d["links"] if l["kind"] == "connect"]
    assert conn, d["links"]
    assert conn[0]["column"] == "קישור" and conn[0]["two_way"] is True
    assert [b["name"] for b in conn[0]["boards"]] == ["יעד"]


def test_the_preview_names_who_would_be_notified(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id, "created_notify_person", {"a_person": guinea_id})
    d = _impact(client, a["id"], admin_id)
    assert d["recipients"] and d["recipients"][0]["ok"] is True
    assert d["recipients"][0]["name"], d["recipients"]

    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    d = _impact(client, a["id"], admin_id)
    assert d["recipients"][0]["ok"] is False
    assert d["missing_permissions"], "a recipient off the board is not flagged"


def test_notify_assignees_is_named_as_a_dynamic_recipient(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "due_notify_assignees", {})
    d = _impact(client, a["id"], admin_id)
    assert any(x["name"] == "משויכי הפריט" for x in d["recipients"]), d["recipients"]


def test_the_preview_names_other_rules_writing_the_same_field(client, admin_id):
    """Two rules setting the status is the thing nobody notices until the board
    starts flipping."""
    bid = _board(client, admin_id)
    first = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
                 name="הראשון", run_order=1)
    second = _add(client, bid, admin_id, "status_notify_assignees", {"t_status": "done"},
                  name="לא מתנגש")
    third = _add(client, bid, admin_id, "assigned_set_status", {"a_status": "in_progress"},
                 name="גם כותב סטטוס", run_order=5)
    d = _impact(client, first["id"], admin_id)
    names = {o["name"]: o for o in d["others"]}
    assert "גם כותב סטטוס" in names, d["others"]
    assert "לא מתנגש" not in names, "a rule that only notifies was called a conflict"
    assert names["גם כותב סטטוס"]["fields"] == ["סטטוס"]
    assert names["גם כותב סטטוס"]["runs_before"] is False     # run_order 5 is after 1


def test_the_preview_warns_about_a_loop(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "status_assign_person", {"t_status": "done",
                                                             "a_person": admin_id})
    _add(client, bid, admin_id, "assigned_set_status", {"a_status": "done"},
         name="מחזיר לסטטוס")
    d = _impact(client, a["id"], admin_id)
    assert d["loop_risk"], "the rule feeding itself was not flagged"
    assert d["loop_risk"][0]["cycle"] is True, d["loop_risk"]


def test_the_preview_follows_the_viewing_permission(client, admin_id, member_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id)
    assert client.get(f"/api/automations/{a['id']}/impact?user_id={member_id}"
                      ).status_code == 403


# ── the dry run ─────────────────────────────────────────────────────────────

def test_it_reports_the_trigger_match(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "critical"}, status="draft")
    tid = _item(client, bid, admin_id)
    d = _dry(client, a["id"], tid, admin_id)
    assert d["trigger"]["matches"] is False, d["trigger"]
    assert d["verdict"] == "would_skip" and "הגורם המפעיל" in d["summary"]

    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    d = _dry(client, a["id"], tid, admin_id)
    assert d["trigger"]["matches"] is True
    assert d["verdict"] == "would_run"


def test_it_reports_each_condition_separately(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    d = _dry(client, a["id"], tid, admin_id)
    assert len(d["conditions"]) == 1
    c = d["conditions"][0]
    assert c["ok"] is False and c["expected"] and c["actual"]
    # rendered as the board shows them, not as keys
    assert c["expected"] != "done", c


def test_it_reports_the_actions_and_the_values_they_would_write(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
             status="draft")
    tid = _item(client, bid, admin_id)
    d = _dry(client, a["id"], tid, admin_id)
    act = d["actions"][0]
    assert act["what"] == "שינוי סטטוס" and act["to"] and act["from"]
    assert act["to"] != "done", "the value was not rendered for a reader"
    assert act["no_op"] is False


def test_it_reports_a_missing_permission(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id, "created_notify_person", {"a_person": guinea_id})
    tid = _item(client, bid, admin_id)
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    d = _dry(client, a["id"], tid, admin_id)
    assert d["verdict"] == "blocked"
    assert d["missing_permissions"] and "אינו חבר בלוח" in d["missing_permissions"][0]


def test_it_reports_a_broken_dependency(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        row.config = {"a_status": "no_such"}
        db.commit()
    tid = _item(client, bid, admin_id)
    d = _dry(client, a["id"], tid, admin_id)
    assert d["verdict"] == "blocked" and d["broken_dependencies"]


def test_it_carries_the_conflict_and_loop_warnings(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"}, name="א")
    _add(client, bid, admin_id, "assigned_set_status", {"a_status": "in_progress"}, name="ב")
    tid = _item(client, bid, admin_id)
    d = _dry(client, a["id"], tid, admin_id)
    assert any(o["name"] == "ב" for o in d["conflicts"]), d["conflicts"]
    assert "loop_risk" in d


def test_it_changes_nothing_and_notifies_nobody(client, admin_id, guinea_id):
    """The old implementation ran the rule and rolled it back. This one never
    writes at all — so there is nothing to roll back and nothing to leak."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id, "created_notify_person", {"a_person": guinea_id},
             status="draft")
    tid = _item(client, bid, admin_id, "פריט שלא ישתנה")
    before_item = client.get(f"/api/tasks/{tid}?user_id={admin_id}").json()
    with Session(cityos_main.engine) as db:
        notes_before = db.query(Notification).filter(Notification.user_id == guinea_id).count()
        runs_before = db.query(AutomationRun).filter(AutomationRun.board_id == bid).count()

    d = _dry(client, a["id"], tid, admin_id)
    assert d["changed_nothing"] is True and d["notified_nobody"] is True

    after_item = client.get(f"/api/tasks/{tid}?user_id={admin_id}").json()
    assert after_item == before_item, "the item moved"
    with Session(cityos_main.engine) as db:
        assert db.query(Notification).filter(
            Notification.user_id == guinea_id).count() == notes_before, "a notification was sent"
        assert db.query(AutomationRun).filter(
            AutomationRun.board_id == bid).count() == runs_before, "a run row was written"
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        assert (row.run_count or 0) == 0 and (row.skip_count or 0) == 0
        assert row.last_run_at is None, "the dry run counted as an attempt"


def test_the_notification_action_says_it_will_not_be_sent(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_notify_person", {"a_person": admin_id})
    tid = _item(client, bid, admin_id)
    d = _dry(client, a["id"], tid, admin_id)
    act = d["actions"][0]
    assert act["what"] == "שליחת התראה"
    assert "לא נשלחת התראה" in act["note"], act


# ── the separate log, and its 30 days ───────────────────────────────────────

def test_a_test_is_kept_with_its_whole_analysis(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"}, status="draft")
    tid = _item(client, bid, admin_id, "פריט ללוג")
    d = _dry(client, a["id"], tid, admin_id)
    log = client.get(f"/api/boards/{bid}/automations/tests?user_id={admin_id}").json()
    assert log["retention_days"] == cityos_main.AUTOMATION_TEST_LOG_DAYS == 30
    row = log["tests"][0]
    assert row["id"] == d["test_id"] and row["task_title"] == "פריט ללוג"
    assert row["verdict"] == "would_run" and row["tested_by_name"]
    # the analysis is re-readable without running it again
    assert row["details"]["trigger"]["matches"] is True
    assert row["details"]["actions"], row["details"]


def test_the_log_can_be_read_per_automation(client, admin_id):
    bid = _board(client, admin_id)
    a1 = _add(client, bid, admin_id, name="א")
    a2 = _add(client, bid, admin_id, name="ב")
    tid = _item(client, bid, admin_id)
    _dry(client, a1["id"], tid, admin_id)
    _dry(client, a2["id"], tid, admin_id)
    d = client.get(f"/api/boards/{bid}/automations/tests"
                   f"?user_id={admin_id}&automation_id={a1['id']}").json()
    assert [t["automation_id"] for t in d["tests"]] == [a1["id"]]


def test_a_test_older_than_thirty_days_is_swept(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    _dry(client, a["id"], tid, admin_id)
    with Session(cityos_main.engine) as db:
        row = (db.query(AutomationTestRun)
                 .filter(AutomationTestRun.board_id == bid).first())
        row.created_at = (datetime.now(timezone.utc).replace(tzinfo=None)
                          - timedelta(days=cityos_main.AUTOMATION_TEST_LOG_DAYS + 1))
        db.commit()
    d = client.get(f"/api/boards/{bid}/automations/tests?user_id={admin_id}").json()
    assert d["tests"] == [], "a test older than the retention window survived"
    with Session(cityos_main.engine) as db:
        assert db.query(AutomationTestRun).filter(
            AutomationTestRun.board_id == bid).count() == 0


def test_the_test_log_follows_the_viewing_permission(client, admin_id, member_id):
    bid = _board(client, admin_id)
    assert client.get(f"/api/boards/{bid}/automations/tests?user_id={member_id}"
                      ).status_code == 403


def test_only_a_board_admin_may_run_a_test(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    assert client.post(f"/api/automations/{a['id']}/test?user_id={guinea_id}",
                       json={"task_id": tid}).status_code == 403


def test_the_screen_shows_the_preview_and_the_analysis():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
           ).read_text(encoding="utf-8")
    # the preview, before switching a rule on
    for marker in ("על מה משפיעה האוטומציה", "שדות נקראים", "שדות מתעדכנים",
                   "תלויות בקישור ובמראה", "נמעני התראות",
                   "אוטומציות נוספות שמעדכנות אותם שדות", "סיכון ללולאה"):
        assert marker in src, f"the preview says nothing about {marker}"
    # the dry run's own sections
    for marker in ("גורם מפעיל", "תנאים", "פעולות וערכים צפויים", "הרשאות חסרות",
                   "תלויות חסרות", "התנגשות",
                   "אינה משנה מידע ואינה שולחת התראה"):
        assert marker in src, f"the dry run says nothing about {marker}"
    # and the test log is its own screen
    assert "אינן בלוג ההפעלות" in src
    assert "Automations.testLog(" in src
