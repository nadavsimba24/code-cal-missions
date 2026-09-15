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
    assert _get(client, bid, a["id"], admin_id)["config"] == {"a_person": admin_id}


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
    """"מושהית עקב שגיאה" names a loop among its causes."""
    bid = _board(client, admin_id)
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})            # depth 1
    _add(client, bid, admin_id, "priority_assign_person",
         {"t_priority": "critical", "a_person": admin_id})          # depth 2
    _add(client, bid, admin_id, "assigned_set_status",
         {"a_status": "in_progress"})                               # depth 3
    _add(client, bid, admin_id, "status_notify_assignees",
         {"t_status": "in_progress"})                               # cut off by the ceiling
    for i in range(cityos_main.AUTOMATION_FAIL_CUTOFF + 1):
        tid = _item(client, bid, admin_id, f"פריט {i}")
        client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        rows = db.query(Automation).filter(Automation.board_id == bid).all()
        hit = [r for r in rows if (r.state or {}).get("loop_hits")]
    assert hit, "nothing recorded being cut off by the depth ceiling"
    assert any(r.status == "paused_error" for r in hit), \
        [(r.id, r.status, (r.state or {}).get("loop_hits")) for r in hit]


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
