"""Group — the seven ownership rules.

  1. The creator owns the rule at creation; ownership moves to another
     authorised manager.
  2. Changing the owner changes neither the creator nor whether the rule runs.
  3. The owner is told about persistent failure, automatic suspension, a deleted
     dependency and a damaged permission.
  4. An owner who is blocked or loses management rights shows as "דורשת שיוך
     בעלים" — with no automatic change to the run status.
  5. The board's managers are asked to appoint a replacement; after 7 days a
     daily escalation goes to the system admin too.
  6. The rule keeps running without an owner while the grant and the
     dependencies hold.
  7. Every handover is in the Audit: previous owner, new owner, who, when.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AuditLog, Notification, Task, User


def _board(client, admin_id, name="לוח בעלות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _member(client, admin_id, bid, uid, role="admin"):
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


def _row(client, bid, aid, uid):
    d = client.get(f"/api/boards/{bid}/automations?user_id={uid}").json()
    return next(a for a in d["automations"] if a["id"] == aid)


def _notes(uid, needle="", board_id=None):
    with Session(cityos_main.engine) as db:
        q = db.query(Notification).filter(Notification.user_id == uid,
                                          Notification.type == "automation")
        if board_id is not None:
            q = q.filter(Notification.board_id == board_id)
        return [n for n in q.all() if needle in (n.title or "")]


# ── rule 1 ──────────────────────────────────────────────────────────────────

def test_rule1_the_creator_owns_it(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id)
    assert a["owner_id"] == admin_id and a["owner_is_creator"] is True
    assert a["needs_owner"] is False


def test_rule1_ownership_moves_only_to_an_authorised_manager(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    aid = _add(client, bid, admin_id)["id"]
    _member(client, admin_id, bid, guinea_id, "editor")
    r = client.patch(f"/api/automations/{aid}?user_id={admin_id}", json={"owner_id": guinea_id})
    assert r.status_code == 400 and "מנהל מורשה" in r.json()["detail"]
    _member(client, admin_id, bid, guinea_id, "admin")
    assert client.patch(f"/api/automations/{aid}?user_id={admin_id}",
                        json={"owner_id": guinea_id}).status_code == 200


# ── rule 2 ──────────────────────────────────────────────────────────────────

def test_rule2_a_handover_changes_neither_the_creator_nor_the_running(client, admin_id,
                                                                     guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id, status="paused")
    got = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                       json={"owner_id": guinea_id}).json()
    assert got["owner_id"] == guinea_id
    assert got["created_by"] == admin_id, "the handover rewrote history"
    assert got["owner_is_creator"] is False
    assert got["status"] == "paused" and got["is_active"] is False, \
        "the handover switched the rule back on"


def test_rule2_a_bulk_handover_does_not_switch_anything_on(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "admin")
    ids = [_add(client, bid, admin_id, status="paused")["id"] for _ in range(2)]
    client.post(f"/api/boards/{bid}/automations/bulk?user_id={admin_id}",
                json={"ids": ids, "action": "transfer", "owner_id": guinea_id})
    with Session(cityos_main.engine) as db:
        for i in ids:
            row = db.query(Automation).filter(Automation.id == i).first()
            assert row.owner_id == guinea_id and row.is_active is False
            assert row.created_by == admin_id


# ── rule 3 ──────────────────────────────────────────────────────────────────

def test_rule3_the_owner_hears_about_a_deleted_dependency_once(client, admin_id):
    """A rule can fire hundreds of times a day; the same notice every firing is
    not a notice."""
    bid = _board(client, admin_id)
    grp = client.post("/api/groups", json={"board_id": bid, "name": "קבוצה",
                                           "actor_id": admin_id}).json()["id"]
    _add(client, bid, admin_id, "status_move_group", {"t_status": "done", "a_group": grp})
    client.delete(f"/api/groups/{grp}?actor_id={admin_id}")
    for i in range(3):
        tid = _item(client, bid, admin_id, f"פריט {i}")
        client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    told = _notes(admin_id, "תלות חסרה", bid)
    assert len(told) == 1, f"the owner was told {len(told)} times"
    assert "נמחקה" in (told[0].body or "")


def test_rule3_a_run_that_works_clears_the_notice(client, admin_id):
    """So the next occurrence is reported again instead of being suppressed."""
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        row.config = {"a_status": "no_such"}
        db.commit()
    _item(client, bid, admin_id, "א")
    assert len(_notes(admin_id, "תלות חסרה", bid)) >= 1
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        assert (row.state or {}).get("told"), "nothing was recorded as told"
        row.config = {"a_status": "done"}
        db.commit()
    _item(client, bid, admin_id, "ב")
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        assert not (row.state or {}).get("told"), "a working run left the notice in place"


def test_rule3_the_owner_hears_about_a_damaged_permission_and_a_suspension(client, admin_id,
                                                                          guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "editor")
    _add(client, bid, admin_id, "created_notify_person", {"a_person": guinea_id})
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    _item(client, bid, admin_id)
    assert _notes(admin_id, "הרשאה חסרה", bid), "the owner was not told the permission broke"


def test_rule3_persistent_failure_reaches_the_owner(client, admin_id, monkeypatch):
    bid = _board(client, admin_id)
    _add(client, bid, admin_id)

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(cityos_main, "_run_action", boom)
    for i in range(cityos_main.AUTOMATION_FAIL_CUTOFF):
        _item(client, bid, admin_id, f"פריט {i}")
    assert _notes(admin_id, "הושהתה עקב שגיאות", bid)


# ── rules 4 and 6 ───────────────────────────────────────────────────────────

def test_rule4_a_blocked_owner_shows_an_indicator_and_changes_no_status(client, admin_id,
                                                                       guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"owner_id": guinea_id})
    assert _row(client, bid, a["id"], admin_id)["needs_owner"] is False

    with Session(cityos_main.engine) as db:                     # the account is blocked
        u = db.query(User).filter(User.id == guinea_id).first()
        u.is_active = False
        db.commit()
    row = _row(client, bid, a["id"], admin_id)
    assert row["needs_owner"] is True and "חסום" in row["owner_problem"]
    assert row["status"] == "active" and row["is_active"] is True, \
        "a blocked owner suspended the rule"
    with Session(cityos_main.engine) as db:
        u = db.query(User).filter(User.id == guinea_id).first()
        u.is_active = True
        db.commit()


def test_rule4_an_owner_who_loses_management_shows_the_same(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"owner_id": guinea_id})
    client.patch(f"/api/boards/{bid}/members/{guinea_id}",
                 json={"actor_id": admin_id, "role": "editor"})
    row = _row(client, bid, a["id"], admin_id)
    assert row["needs_owner"] is True and "אינו מנהל הלוח" in row["owner_problem"]
    assert row["is_active"] is True


def test_rule6_a_rule_with_no_owner_keeps_running(client, admin_id, guinea_id):
    """Answerability is missing; the rule is not."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"owner_id": guinea_id})
    client.patch(f"/api/boards/{bid}/members/{guinea_id}",
                 json={"actor_id": admin_id, "role": "editor"})
    assert _row(client, bid, a["id"], admin_id)["needs_owner"] is True

    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._st_of(t) == "done", "an unowned rule stopped working"


# ── rule 5 ──────────────────────────────────────────────────────────────────

def test_rule5_the_boards_managers_are_asked_to_appoint_someone(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id)
    with Session(cityos_main.engine) as db:                 # its owner is blocked
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        row.owner_id = None
        row.created_by = None
        db.commit()
    client.get(f"/api/boards/{bid}/automations?user_id={admin_id}")     # the screen sweeps
    for uid in (admin_id, guinea_id):
        told = _notes(uid, "דורשת שיוך בעלים", bid)
        assert told, f"board manager {uid} was not asked"
        assert "למנות בעלים חלופי" in (told[0].body or "")
        assert "ממשיכה לפעול" in (told[0].body or ""), "the notice did not say it still runs"
    # asked once, not on every read
    client.get(f"/api/boards/{bid}/automations?user_id={admin_id}")
    assert len(_notes(admin_id, "דורשת שיוך בעלים", bid)) == 1


def test_rule5_after_seven_days_the_system_admin_is_escalated_to_daily(client, admin_id):
    bid = _board(client, admin_id, "לוח הסלמה")
    a = _add(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        row.owner_id = None
        row.created_by = None
        db.commit()
    client.get(f"/api/boards/{bid}/automations?user_id={admin_id}")
    assert not _notes(admin_id, "הסלמה", bid), "escalated on day one"

    with Session(cityos_main.engine) as db:                 # backdate the gap
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        st = dict(row.state or {})
        st["owner_gap_since"] = (datetime.now(timezone.utc).replace(tzinfo=None)
                                 - timedelta(days=cityos_main.AUTOMATION_OWNER_ESCALATION_DAYS
                                             + 1)).isoformat()
        row.state = st
        db.commit()
    client.get(f"/api/boards/{bid}/automations?user_id={admin_id}")
    esc = _notes(admin_id, "הסלמה", bid)
    assert esc, "no escalation after the window"
    assert "ימים ללא בעלים" in (esc[0].body or "")
    # daily, not on every read
    client.get(f"/api/boards/{bid}/automations?user_id={admin_id}")
    assert len(_notes(admin_id, "הסלמה", bid)) == 1


def test_rule5_appointing_an_owner_ends_the_chase(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        row.owner_id = None
        row.created_by = None
        db.commit()
    client.get(f"/api/boards/{bid}/automations?user_id={admin_id}")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"owner_id": guinea_id})
    client.get(f"/api/boards/{bid}/automations?user_id={admin_id}")
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        assert not (row.state or {}).get("owner_gap_since"), "the gap was not closed"
        assert not (row.state or {}).get("owner_told")
    assert _row(client, bid, a["id"], admin_id)["needs_owner"] is False


# ── rule 7 ──────────────────────────────────────────────────────────────────

def test_rule7_every_handover_is_in_the_audit(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"owner_id": guinea_id})
    with Session(cityos_main.engine) as db:
        logs = db.query(AuditLog).filter(AuditLog.entity_type == "automation",
                                         AuditLog.entity_id == a["id"],
                                         AuditLog.action == "transfer_owner").all()
        assert len(logs) == 1, logs
        l = logs[0]
        assert str(admin_id) in (l.old_value or ""), l.old_value      # previous owner
        assert str(guinea_id) in (l.new_value or ""), l.new_value     # new owner
        assert l.changed_by == admin_id                               # who did it
        assert l.created_at is not None                               # and when
        assert l.field_name == "owner_id"


def test_rule7_a_bulk_handover_is_audited_per_rule(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "admin")
    ids = [_add(client, bid, admin_id)["id"] for _ in range(3)]
    client.post(f"/api/boards/{bid}/automations/bulk?user_id={admin_id}",
                json={"ids": ids, "action": "transfer", "owner_id": guinea_id})
    with Session(cityos_main.engine) as db:
        logs = db.query(AuditLog).filter(AuditLog.entity_type == "automation",
                                         AuditLog.action == "transfer_owner",
                                         AuditLog.entity_id.in_(ids)).all()
    assert len(logs) == 3, f"{len(logs)} audit rows for 3 handovers"


def test_rule7_a_patch_that_does_not_move_the_owner_writes_nothing(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"owner_id": admin_id, "name": "שם"})
    with Session(cityos_main.engine) as db:
        assert db.query(AuditLog).filter(AuditLog.entity_type == "automation",
                                         AuditLog.entity_id == a["id"],
                                         AuditLog.action == "transfer_owner").count() == 0
