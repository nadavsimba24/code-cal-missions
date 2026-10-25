"""Group — drafts, versions and what an activation actually means.

  · A draft may hold an incomplete configuration; switching it on may not.
  · An activation applies to events from the moment of activation.
  · Editing an ACTIVE rule writes a draft version; the version in force keeps
    running until the new one is published explicitly.
  · A run already begun finishes under the version in force when the event
    arrived — and the log says which version that was.
  · Every save is a version, and a comparison groups the changes into trigger,
    conditions, actions, permissions and order.
  · A restore produces a draft, which is checked like any activation.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AutomationRun, AutomationVersion, Task


def _board(client, admin_id, name="לוח מחזור חיים"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _add(client, bid, admin_id, recipe_id="created_set_priority", config=None, **extra):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id, "config": config or {"a_priority": "high"},
                          **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _get(client, bid, aid, admin_id):
    d = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
    return next(a for a in d["automations"] if a["id"] == aid)


# ── a draft may be incomplete; an active rule may not ───────────────────────

def test_a_draft_can_be_saved_half_built(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "status_notify_person",
                          "config": {"t_status": "done"},          # no recipient yet
                          "status": "draft"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["status"] == "draft" and a["config"] == {"t_status": "done"}
    assert a["missing_fields"] == ["נמען"], a["missing_fields"]


def test_the_same_rule_cannot_be_created_active(client, admin_id):
    bid = _board(client, admin_id)
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "status_notify_person",
                          "config": {"t_status": "done"}})
    assert r.status_code == 400 and "נמען" in r.json()["detail"]


def test_an_incomplete_draft_refuses_to_be_switched_on(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    a = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "status_notify_person",
                          "config": {"t_status": "done"}, "status": "draft"}).json()
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "active"})
    assert r.status_code == 400
    assert "חסרים שדות חובה" in r.json()["detail"] and "נמען" in r.json()["detail"]

    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"config": {"t_status": "done", "a_person": guinea_id}})
    assert client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                        json={"status": "active"}).status_code == 200


def test_a_draft_whose_dependency_is_gone_refuses_to_be_switched_on(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"}, status="draft")
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        row.config = {"a_status": "no_such_status"}
        db.commit()
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "active"})
    assert r.status_code == 400 and "אינו קיים בלוח" in r.json()["detail"]


def test_a_draft_does_not_listen_to_events(client, admin_id):
    bid = _board(client, admin_id)
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"}, status="draft")
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) != "done"


# ── an activation applies from the moment of activation ─────────────────────

def test_activation_does_not_reach_backwards(client, admin_id):
    """A due-date rule switched on today must not fire at everything that was
    already overdue — that reads as the rule inventing history."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id, "היה באיחור מזמן")
    client.patch(f"/api/tasks/{tid}", json={"due_date": "2025-01-01", "user_id": admin_id})
    a = _add(client, bid, admin_id, "due_notify_assignees", {})
    client.post(f"/api/tasks/{tid}/assignees", json={"actor_id": admin_id, "user_id": admin_id})
    client.get(f"/api/boards/{bid}?user_id={admin_id}")            # the sweep runs on read
    runs = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}"
                      ).json()["runs"]
    assert not [r for r in runs if r["automation_id"] == a["id"]], \
        "the rule acted on a date that arrived before it was switched on"

    with Session(cityos_main.engine) as db:                        # as if it had been on
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        row.activated_at = datetime(2024, 1, 1)
        db.commit()
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    runs = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}"
                      ).json()["runs"]
    assert [r for r in runs if r["automation_id"] == a["id"]], "it never fired at all"


def test_the_moment_of_activation_is_recorded(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, status="draft")
    assert a["activated_at"] is None
    on = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                      json={"status": "active"}).json()
    assert on["activated_at"], "nothing recorded when the rule was switched on"


# ── editing a live rule writes a draft version ──────────────────────────────

def test_editing_an_active_rule_does_not_change_what_runs(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    got = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                       json={"config": {"a_status": "in_progress"}}).json()
    assert got["draft_version"], "the edit did not become a draft"
    assert got["config"] == {"a_status": "done"}, "the live rule was edited under the board"

    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        # still the OLD version's behaviour
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) == "done"


def test_publishing_puts_the_new_version_into_force(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"config": {"a_status": "in_progress"}})
    live = client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}").json()
    assert live["config"] == {"a_status": "in_progress"} and live["draft_version"] is None

    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) == "in_progress"


def test_a_draft_that_would_not_work_cannot_be_published(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    a = _add(client, bid, admin_id, "created_notify_person", {"a_person": admin_id})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"config": {"a_person": guinea_id}})
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    r = client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}")
    assert r.status_code == 400, "a draft naming someone off the board was published"
    assert "ללוח" in r.json()["detail"], r.json()
    # a recipient is stored as WHICH KIND it is — a named person is one of five
    assert _get(client, bid, a["id"], admin_id)["config"] == {
        "a_person": {"kind": "user", "value": admin_id}}


def test_a_draft_can_be_thrown_away_and_the_rule_never_moved(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"config": {"a_status": "in_progress"}})
    got = client.post(f"/api/automations/{a['id']}/discard-draft?user_id={admin_id}").json()
    assert got["draft_version"] is None and got["config"] == {"a_status": "done"}
    # the draft stays in the history, marked as one
    v = client.get(f"/api/automations/{a['id']}/versions?user_id={admin_id}").json()["versions"]
    assert any(x["summary"].startswith("טיוטת עריכה") for x in v), v


def test_a_paused_rule_is_edited_in_place(client, admin_id):
    """There is nothing running to protect."""
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"}, status="paused")
    got = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                       json={"config": {"a_status": "in_progress"}}).json()
    assert got["draft_version"] is None
    assert got["config"] == {"a_status": "in_progress"}


def test_metadata_is_not_held_back_by_the_draft_rule(client, admin_id):
    """A name is not behaviour; holding it for a publish would be absurd."""
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, name="לפני")
    got = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                       json={"name": "אחרי", "importance": "critical"}).json()
    assert got["name"] == "אחרי" and got["importance"] == "critical"
    assert got["draft_version"] is None


# ── the run says which version decided it ───────────────────────────────────

def test_a_run_records_the_version_in_force(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    _item(client, bid, admin_id, "ראשון")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"config": {"a_status": "in_progress"}})
    client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}")
    _item(client, bid, admin_id, "שני")
    with Session(cityos_main.engine) as db:
        rows = (db.query(AutomationRun).filter(AutomationRun.automation_id == a["id"])
                  .order_by(AutomationRun.id).all())
    versions = [r.version for r in rows]
    assert versions[0] and versions[-1] and versions[-1] > versions[0], versions


# ── every save is a version, and a comparison groups the changes ────────────

def test_a_comparison_groups_the_changes_the_way_the_decision_is_made(client, admin_id,
                                                                     guinea_id):
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    a = _add(client, bid, admin_id, "status_notify_person",
             {"t_status": "done", "a_person": admin_id}, importance="low")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"config": {"t_status": "in_progress", "a_person": guinea_id},
                       "run_order": 5, "importance": "critical"})
    d = client.get(f"/api/automations/{a['id']}/versions/compare?user_id={admin_id}").json()
    groups = {g["id"]: g for g in d["groups"]}
    assert "conditions" in groups, d
    assert "permissions" in groups, "a change of recipient is a change of permissions"
    assert "order" in groups
    cond = groups["conditions"]["changes"][0]
    assert cond["from"] and cond["to"] and cond["from"] != cond["to"]
    # rendered as the board shows them, not as ids
    perm = groups["permissions"]["changes"][0]
    assert not perm["to"].isdigit(), perm


def test_a_comparison_of_two_identical_versions_says_so(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id)
    d = client.get(f"/api/automations/{a['id']}/versions/compare"
                   f"?user_id={admin_id}&a=1&b=1").json()
    assert d["identical"] is True and d["groups"] == []


def test_the_comparison_follows_the_viewing_permission(client, admin_id, member_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id)
    assert client.get(f"/api/automations/{a['id']}/versions/compare"
                      f"?user_id={member_id}").status_code == 403


# ── a restore is a draft, checked like any activation ───────────────────────

def test_a_restore_is_a_draft_and_the_publish_checks_it(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    a = _add(client, bid, admin_id, "created_notify_person", {"a_person": guinea_id})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"config": {"a_person": admin_id}})
    client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}")

    # the old version named someone who has since left the board
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    back = client.post(f"/api/automations/{a['id']}/restore/1?user_id={admin_id}")
    assert back.status_code == 200 and back.json()["draft_version"], back.text
    r = client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}")
    assert r.status_code == 400, "a restored version that cannot work was published"
    assert "ללוח" in r.json()["detail"], r.json()


# ── the statuses ────────────────────────────────────────────────────────────

def test_the_five_statuses_are_the_five_in_the_spec(client):
    assert set(cityos_main.AUTOMATION_STATUSES) == {
        "draft", "active", "paused", "paused_error", "deleting"}


def test_a_loop_suspends_the_rule_as_the_status_table_says(client, admin_id):
    """"מושהית עקב שגיאה" names a loop among its causes.

    A rule cut off once is a rule that happened to be at the end of a long
    chain. A rule cut off five times running is in a loop, and leaving it
    active means the board reads as automated while this never completes.
    """
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "critical"})
    for i in range(cityos_main.AUTOMATION_FAIL_CUTOFF):
        tid = _item(client, bid, admin_id, f"פריט {i}")
        with Session(cityos_main.engine) as db:
            t = db.query(Task).filter(Task.id == tid).first()
            cityos_main._run_automations(
                db, t, cityos_main._event("status_changes_to", "item", status="done",
                                          chain_runs=cityos_main.AUTOMATION_CHAIN_MAX_RUNS),
                admin_id)
            db.commit()
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        assert (row.state or {}).get("loop_hits"), "nothing recorded being cut off"
        assert row.status == "paused_error", row.status


def test_a_rule_in_deletion_stops_listening(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "deleting"})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) != "done"


def test_the_screen_carries_the_lifecycle():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
           ).read_text(encoding="utf-8")
    for marker in ("ממתינה להפעלה", "ממשיכה לפעול עד שתפעילו", "Automations.publish(",
                   "Automations.discard(", "Automations.compare(", "חסרים שדות חובה",
                   "אין הבדל בין הגרסאות"):
        assert marker in src, f"the screen says nothing about {marker}"
    # a draft may be saved half-built, so that button is never disabled
    i = src.index("שמור כטיוטה")
    assert "disabled" not in src[i - 120:i], "the draft button is gated on completeness"


# ── the two ways past the explicit publish ─────────────────────────────────
# "הגרסה הקודמת תמשיך לפעול עד להפעלה מפורשת של החדשה" is the whole of the
# third rule, and the save that edits an active rule carried a `publish` flag
# that skipped it: the edit went straight into force, with no draft to read
# first and none of the checks the publish does. No screen ever sent it.

def _member(client, admin_id, bid, uid, role="editor"):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    assert r.status_code == 200, r.text


def test_an_edit_to_an_active_rule_always_waits_for_a_publish(client, admin_id):
    bid = _board(client, admin_id, "לוח קיצור דרך")
    a = _add(client, bid, admin_id)                       # active, עדיפות גבוהה
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                     json={"config": {"a_priority": "low"}, "publish": True})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["draft_version"], "the edit went into force with no draft"
    assert got["config"]["a_priority"] == "high", \
        "the running rule changed under a flag instead of a publish"
    assert _get(client, bid, a["id"], admin_id)["config"]["a_priority"] == "high"
    # and the explicit publish is still the way in
    assert client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}"
                       ).json()["config"]["a_priority"] == "low"


# ── one bar for switching a rule on, whichever button does it ──────────────
# The switch re-derives everything the engine checks before a run. The bulk
# "הפעל" had a health check of its own that read only the recipe's own action —
# so a rule whose SECOND action names somebody who left the board passed it,
# and a screenful of rules that will skip every time went back on looking like
# it had worked.

def test_a_bulk_activation_holds_the_same_bar_as_the_switch(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח הפעלה מרובה")
    _member(client, admin_id, bid, member_id, "editor")
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "notify_person", "values": {"person": member_id}}]},
             status="paused")
    client.delete(f"/api/boards/{bid}/members/{member_id}?actor_id={admin_id}")

    one = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                       json={"status": "active"})
    assert one.status_code == 400, one.text          # the switch refuses it

    r = client.post(f"/api/boards/{bid}/automations/bulk?user_id={admin_id}",
                    json={"ids": [a["id"]], "action": "activate"})
    assert r.status_code == 200, r.text
    row = r.json()["results"][0]
    assert row["ok"] is False, row
    assert "חבר בלוח" in row["message"] or "מושבת" in row["message"], row
    assert _get(client, bid, a["id"], admin_id)["status"] != "active", \
        "the bulk action switched on a rule the switch had just refused"


def test_a_bulk_activation_still_switches_on_a_rule_that_is_fine(client, admin_id):
    bid = _board(client, admin_id, "לוח הפעלה מרובה תקינה")
    a = _add(client, bid, admin_id, status="paused")
    r = client.post(f"/api/boards/{bid}/automations/bulk?user_id={admin_id}",
                    json={"ids": [a["id"]], "action": "activate"})
    assert r.json()["results"][0]["ok"] is True, r.json()
    assert _get(client, bid, a["id"], admin_id)["status"] == "active"


# ── the status table, line by line ─────────────────────────────────────────
#   טיוטה              אינה מאזינה לאירועים, ומחזיקה הגדרה חלקית
#   פעילה              תקינה ומאזינה
#   מושהית             נעצרה ידנית ואינה קולטת אירועים חדשים
#   מושהית עקב שגיאה   נעצרה בשל תלות, הרשאה, לולאה או כשלים חוזרים
#   בתהליך מחיקה       אינה קולטת אירועים
# and "דורשת שיוך בעלים" is none of them — it is an operational indicator that
# sits alongside the status, so a rule can be פעילה and need an owner at once.

def test_a_paused_rule_does_not_listen_to_events(client, admin_id):
    bid = _board(client, admin_id, "לוח מושהית")
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"}, status="paused")
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) != "done"


def test_a_missing_dependency_suspends_the_rule_as_the_status_table_says(client, admin_id):
    """"נעצרה בשל תלות" — the first of the four causes the table names.

    It used to skip and leave the rule active: the thinking was that a status
    somebody removed makes THIS firing pointless rather than the rule wrong. But
    a dependency does not come back on its own, so what that produced was a rule
    reading as "פעילה" while skipping every single event — which is the thing
    the suspended state exists to stop.
    """
    bid = _board(client, admin_id, "לוח תלות")
    grp = client.post("/api/groups", json={"board_id": bid, "name": "קבוצה",
                                           "actor_id": admin_id}).json()["id"]
    a = _add(client, bid, admin_id, "status_move_group", {"t_status": "done", "a_group": grp})
    client.delete(f"/api/groups/{grp}?actor_id={admin_id}")
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})

    row = _get(client, bid, a["id"], admin_id)
    assert row["status"] == "paused_error", row["status"]
    assert row["is_active"] is False
    # It is stopped by the DELETION now, not by the first firing that trips over
    # the hole — so there is no skipped run to read, and the thing to check is
    # that the Audit says what broke. The engine's own re-check is still there
    # underneath; it is tested where the dependency vanishes without going
    # through an endpoint (see test_automations_rules.py).
    with Session(cityos_main.engine) as db:
        from models import AuditLog
        marks = db.query(AuditLog).filter(AuditLog.entity_type == "automation",
                                          AuditLog.entity_id == a["id"],
                                          AuditLog.action == "dependency_broken").all()
    assert marks, "the broken dependency was not written down"
    assert "קבוצה" in (marks[0].field_name or ""), marks[0].field_name


def test_the_four_causes_of_a_suspension_all_reach_the_same_status(client, admin_id,
                                                                    guinea_id, monkeypatch):
    """תלות, הרשאה, לולאה, כשלים חוזרים — one status, four ways in. The loop
    has a test of its own above; these are the other three."""
    # הרשאה
    bid = _board(client, admin_id, "לוח הרשאה")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    a = _add(client, bid, admin_id, "created_notify_person", {"a_person": guinea_id})
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    _item(client, bid, admin_id)
    assert _get(client, bid, a["id"], admin_id)["status"] == "paused_error"

    # כשלים חוזרים
    bid2 = _board(client, admin_id, "לוח כשלים")
    b = _add(client, bid2, admin_id)
    monkeypatch.setattr(cityos_main, "_run_action",
                        lambda *x, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    for i in range(cityos_main.AUTOMATION_FAIL_CUTOFF):
        _item(client, bid2, admin_id, f"פריט {i}")
    monkeypatch.undo()
    assert _get(client, bid2, b["id"], admin_id)["status"] == "paused_error"


def test_needing_an_owner_is_an_indicator_beside_the_status_not_one_of_them(
        client, admin_id, guinea_id):
    assert "needs_owner" not in cityos_main.AUTOMATION_STATUSES
    bid = _board(client, admin_id, "לוח חיווי")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    a = _add(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"owner_id": guinea_id})
    client.patch(f"/api/boards/{bid}/members/{guinea_id}",
                 json={"actor_id": admin_id, "role": "editor"})
    row = _get(client, bid, a["id"], admin_id)
    assert row["status"] == "active" and row["is_active"] is True
    assert row["needs_owner"] is True and row["owner_problem"]


def test_the_screen_carries_the_status_table():
    """The screen already said what each status means — it was the engine that
    did not keep one of the promises. The two are checked together so they
    cannot drift apart again."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
           ).read_text(encoding="utf-8")
    for he, what in (
            ("טיוטה", "אינה מאזינה לאירועים"),
            ("פעילה", "תקינה ומאזינה לאירועים"),
            ("מושהית", "נעצרה ידנית ואינה קולטת אירועים חדשים"),
            ("מושהית עקב שגיאה", "נעצרה בשל תלות, הרשאה, לולאה או כשלים חוזרים"),
            ("בתהליך מחיקה", "אינה קולטת אירועים")):
        assert what in src, f"the screen does not say what {he} means"
    # and the indicator is never offered as one of them
    assert "דורשת שיוך בעלים" in src and "needs_owner" in src
