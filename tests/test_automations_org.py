"""Group — governing automations across the organisation (ניהול ארגוני).

A board admin could always see their own board. Nobody could see the
organisation: how many rules exist, which answer to nobody, which have not
fired in months, which are failing, and how much they consume. Plus the two
actions that view exists for — an emergency stop, and acting on several rules
at once without a bulk delete.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AuditLog, AutomationFreeze, AutomationUsage, Board, Task, User


def _board(client, admin_id, name="לוח", invite=None):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    if invite is not None:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": invite, "role": "editor"})
    return bid


def _add(client, bid, admin_id, recipe_id="created_set_priority", config=None, **extra):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id,
                             "config": config or {"a_priority": "high"}, **extra}).json()


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _org(client, admin_id, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    return client.get(f"/api/admin/automations?user_id={admin_id}{qs}").json()


# ── who may look ────────────────────────────────────────────────────────────

def test_the_organisational_view_is_for_a_system_admin_only(client, admin_id, guinea_id):
    """It is every board's rules at once, including boards the reader was never
    invited to."""
    assert client.get(f"/api/admin/automations?user_id={admin_id}").status_code == 200
    assert client.get(f"/api/admin/automations?user_id={guinea_id}").status_code == 403
    assert client.get(f"/api/admin/automations/export?user_id={guinea_id}").status_code == 403


def test_it_shows_rules_from_boards_across_the_organisation(client, admin_id):
    b1 = _board(client, admin_id, "לוח א")
    b2 = _board(client, admin_id, "לוח ב")
    a1 = _add(client, b1, admin_id, name="כלל א")
    a2 = _add(client, b2, admin_id, name="כלל ב")
    d = _org(client, admin_id)
    found = {r["id"]: r for r in d["automations"]}
    assert a1["id"] in found and a2["id"] in found
    assert found[a1["id"]]["board_name"] == "לוח א"
    assert d["totals"]["boards"] >= 2


def test_every_row_names_its_board_and_its_organisational_unit(client, admin_id):
    bid = _board(client, admin_id, "לוח יחידה")
    aid = _add(client, bid, admin_id)["id"]
    row = next(r for r in _org(client, admin_id)["automations"] if r["id"] == aid)
    assert row["board_name"] == "לוח יחידה"
    assert "department_id" in row and "department_name" in row


# ── the three things the page exists to find ────────────────────────────────

def test_a_rule_whose_owner_left_the_board_counts_as_ownerless(client, admin_id, guinea_id):
    """Not only a null column: a rule whose owner is off the board it acts on,
    or no longer a manager of it, answers to nobody in practice."""
    bid = _board(client, admin_id, invite=guinea_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    aid = _add(client, bid, admin_id)["id"]
    r = client.patch(f"/api/automations/{aid}?user_id={admin_id}", json={"owner_id": guinea_id})
    assert r.status_code == 200, r.text
    row = next(r for r in _org(client, admin_id)["automations"] if r["id"] == aid)
    assert row["ownerless"] is False

    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    row = next(r for r in _org(client, admin_id)["automations"] if r["id"] == aid)
    assert row["ownerless"] is True, "an owner who left the board still counted as an owner"
    assert next(r for r in _org(client, admin_id, flag="ownerless")["automations"]
                if r["id"] == aid)


def test_a_rule_that_has_not_run_in_90_days_is_stale(client, admin_id):
    bid = _board(client, admin_id)
    aid = _add(client, bid, admin_id)["id"]
    row = next(r for r in _org(client, admin_id)["automations"] if r["id"] == aid)
    assert row["stale"] is True and row["stale_days"] is None, "never run counts as stale"

    _item(client, bid, admin_id)                      # now it has run
    row = next(r for r in _org(client, admin_id)["automations"] if r["id"] == aid)
    assert row["stale"] is False and row["stale_days"] == 0

    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == aid).first()
        a.last_run_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=91)
        db.commit()
    row = next(r for r in _org(client, admin_id)["automations"] if r["id"] == aid)
    assert row["stale"] is True and row["stale_days"] == 91
    assert aid in {r["id"] for r in _org(client, admin_id, flag="stale")["automations"]}


def test_a_failing_rule_is_flagged_and_counted(client, admin_id, monkeypatch):
    bid = _board(client, admin_id)
    aid = _add(client, bid, admin_id)["id"]

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(cityos_main, "_run_action", boom)
    _item(client, bid, admin_id)
    monkeypatch.undo()

    d = _org(client, admin_id)
    row = next(r for r in d["automations"] if r["id"] == aid)
    assert row["needs_attention"] is True and row["fail_count"] == 1
    assert d["totals"]["failures"] >= 1
    assert aid in {r["id"] for r in _org(client, admin_id, flag="attention")["automations"]}


def test_the_tiles_stay_over_the_whole_organisation_when_filtered(client, admin_id):
    """Narrowing the list must not change the totals being narrowed."""
    b1, b2 = _board(client, admin_id, "א"), _board(client, admin_id, "ב")
    _add(client, b1, admin_id)
    _add(client, b2, admin_id)
    wide = _org(client, admin_id)
    narrow = _org(client, admin_id, board_id=b1)
    assert narrow["totals"] == wide["totals"]
    assert len(narrow["automations"]) < len(wide["automations"])


# ── quota ───────────────────────────────────────────────────────────────────

def test_consumption_is_counted_per_month_and_per_board(client, admin_id):
    bid = _board(client, admin_id, "לוח מכסה")
    _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"})
    for i in range(3):
        _item(client, bid, admin_id, f"פריט {i}")
    q = _org(client, admin_id)["quota"]
    assert q["period"] == datetime.now(timezone.utc).strftime("%Y-%m")
    assert q["ran"] >= 3 and q["used"] >= 3 and q["limit"] > 0
    assert q["percent"] is not None
    runs = [t["runs"] for t in q["top_boards"]]
    assert len(runs) <= 5 and runs == sorted(runs, reverse=True), q["top_boards"]
    with Session(cityos_main.engine) as db:
        u = db.query(AutomationUsage).filter(
            AutomationUsage.board_id == bid,
            AutomationUsage.period == q["period"]).first()
    assert u and u.ran >= 3, "this board's own month was not counted"


def test_the_quota_does_not_depend_on_the_run_log_that_gets_trimmed(client, admin_id):
    """The log is capped per board. A quota read off it would shrink as the log
    rolled over, which is the one thing a quota must not do."""
    bid = _board(client, admin_id)
    _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"})
    _item(client, bid, admin_id)
    before = _org(client, admin_id)["quota"]["used"]
    with Session(cityos_main.engine) as db:
        from models import AutomationRun
        db.query(AutomationRun).filter(AutomationRun.board_id == bid).delete()
        db.commit()
    assert _org(client, admin_id)["quota"]["used"] == before


# ── the emergency stop ──────────────────────────────────────────────────────

def test_a_board_freeze_stops_its_rules_without_changing_them(client, admin_id):
    bid = _board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"})["id"]
    r = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "board", "board_id": bid, "reason": "חשד ללופ"})
    assert r.status_code == 200, r.text
    assert r.json()["freeze"]["scope"] == "board" and r.json()["affected"] >= 1

    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._st_of(t) != "in_progress", "a frozen board still fired"
        a = db.query(Automation).filter(Automation.id == aid).first()
        # the rules are untouched, so releasing puts the board back as it was
        assert a.status == "active" and a.is_active is True

    fid = r.json()["freeze"]["id"]
    client.post(f"/api/admin/automations/release?user_id={admin_id}",
                json={"freeze_id": fid, "reason": "נבדק"})
    tid2 = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid2).first()
        assert cityos_main._st_of(t) == "in_progress", "release did not put it back"


def test_an_org_freeze_stops_every_board(client, admin_id):
    b1, b2 = _board(client, admin_id, "א"), _board(client, admin_id, "ב")
    for b in (b1, b2):
        _add(client, b, admin_id, "created_set_status", {"a_status": "in_progress"})
    r = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "org", "reason": "תקלה רוחבית בייצור", "confirm": True})
    assert r.status_code == 200, r.text
    for b in (b1, b2):
        tid = _item(client, b, admin_id)
        with Session(cityos_main.engine) as db:
            t = db.query(Task).filter(Task.id == tid).first()
            assert cityos_main._st_of(t) != "in_progress", f"board {b} still fired"
    client.post(f"/api/admin/automations/release?user_id={admin_id}",
                json={"freeze_id": r.json()["freeze"]["id"]})


def test_an_org_freeze_needs_a_reason_and_a_second_confirmation(client, admin_id):
    no_confirm = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                             json={"scope": "org", "reason": "תקלה רוחבית בייצור"})
    assert no_confirm.status_code == 400 and "אישור" in no_confirm.json()["detail"]
    short = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                        json={"scope": "org", "reason": "כי", "confirm": True})
    assert short.status_code == 400 and "סיבה" in short.json()["detail"]
    none = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                       json={"scope": "org", "confirm": True})
    assert none.status_code == 400


def test_a_board_freeze_still_needs_a_reason(client, admin_id):
    bid = _board(client, admin_id)
    r = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "board", "board_id": bid})
    assert r.status_code == 400


def test_a_freeze_is_written_to_the_audit_log_and_never_expires(client, admin_id):
    bid = _board(client, admin_id)
    r = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "board", "board_id": bid, "reason": "בדיקה ידנית"})
    fid = r.json()["freeze"]["id"]
    with Session(cityos_main.engine) as db:
        logs = db.query(AuditLog).filter(AuditLog.entity_type == "automation_freeze",
                                         AuditLog.entity_id == fid).all()
        assert [l.action for l in logs] == ["create"]
        assert logs[0].changed_by == admin_id and "בדיקה ידנית" in (logs[0].new_value or "")
        f = db.query(AutomationFreeze).filter(AutomationFreeze.id == fid).first()
        # backdating it changes nothing: only a person ends a freeze
        f.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        db.commit()
    assert cityos_main is not None
    assert client.get(f"/api/admin/automations?user_id={admin_id}").json()["freezes"], \
        "a month-old freeze released itself"
    client.post(f"/api/admin/automations/release?user_id={admin_id}", json={"freeze_id": fid})
    with Session(cityos_main.engine) as db:
        logs = [l.action for l in db.query(AuditLog)
                .filter(AuditLog.entity_type == "automation_freeze",
                        AuditLog.entity_id == fid).order_by(AuditLog.id).all()]
    assert logs == ["create", "release"]


def test_the_same_freeze_cannot_be_imposed_twice(client, admin_id):
    bid = _board(client, admin_id)
    first = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                        json={"scope": "board", "board_id": bid, "reason": "פעם אחת"})
    again = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                        json={"scope": "board", "board_id": bid, "reason": "פעם שנייה"})
    assert again.status_code == 400
    client.post(f"/api/admin/automations/release?user_id={admin_id}",
                json={"freeze_id": first.json()["freeze"]["id"]})


def test_only_a_system_admin_may_freeze_or_release(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=guinea_id)
    r = client.post(f"/api/admin/automations/freeze?user_id={guinea_id}",
                    json={"scope": "board", "board_id": bid, "reason": "לא מורשה"})
    assert r.status_code == 403
    assert client.post(f"/api/admin/automations/release?user_id={guinea_id}",
                       json={"freeze_id": 1}).status_code == 403


# ── the export ──────────────────────────────────────────────────────────────

def test_the_export_is_the_filtered_list(client, admin_id):
    b1 = _board(client, admin_id, "לוח ייצוא")
    b2 = _board(client, admin_id, "לוח אחר")
    _add(client, b1, admin_id, name="נכנס לייצוא")
    _add(client, b2, admin_id, name="לא נכנס")
    r = client.get(f"/api/admin/automations/export?user_id={admin_id}&board_id={b1}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    assert "נכנס לייצוא" in body and "לא נכנס" not in body
    assert "יחידה ארגונית" in body.splitlines()[0]


# ── bulk actions for a board admin (פעולות מרובות) ──────────────────────────

def _bulk(client, bid, admin_id, ids, action, **extra):
    return client.post(f"/api/boards/{bid}/automations/bulk?user_id={admin_id}",
                       json={"ids": ids, "action": action, **extra})


def test_a_preview_touches_nothing_and_says_what_it_would_do(client, admin_id):
    """The confirmation has to state the count before anything moves."""
    bid = _board(client, admin_id)
    ids = [_add(client, bid, admin_id, name=f"כלל {i}")["id"] for i in range(3)]
    d = _bulk(client, bid, admin_id, ids, "pause", dry_run=True).json()
    assert d["dry_run"] is True and d["affected"] == 3
    assert len(d["results"]) == 3
    assert any("יפסיקו לפעול" in w for w in d["warnings"]), d["warnings"]
    with Session(cityos_main.engine) as db:
        assert all(db.query(Automation).filter(Automation.id == i).first().is_active
                   for i in ids), "the preview changed something"


def test_pausing_several_rules_reports_one_line_each(client, admin_id):
    """"12 rules updated" hides the two that did not."""
    bid = _board(client, admin_id)
    ids = [_add(client, bid, admin_id, name=f"כלל {i}")["id"] for i in range(3)]
    client.patch(f"/api/automations/{ids[2]}?user_id={admin_id}", json={"status": "paused"})
    d = _bulk(client, bid, admin_id, ids, "pause").json()
    by_id = {r["id"]: r for r in d["results"]}
    assert d["affected"] == 3 and d["ok"] == 3 and d["failed"] == 0
    assert by_id[ids[0]]["message"] == "הושהתה"
    assert by_id[ids[2]]["message"] == "מושהית כבר"
    with Session(cityos_main.engine) as db:
        assert not any(db.query(Automation).filter(Automation.id == i).first().is_active
                       for i in ids)


def test_activating_runs_a_health_check_first(client, admin_id, guinea_id):
    """A rule naming someone who left the board will skip every time it fires.
    Switching a screenful of those back on looks like it worked."""
    bid = _board(client, admin_id, invite=guinea_id)
    ok_id = _add(client, bid, admin_id, name="בריאה", status="paused")["id"]
    bad_id = _add(client, bid, admin_id, "created_notify_person", {"a_person": guinea_id},
                  name="נמען שעזב", status="paused")["id"]
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")

    prev = _bulk(client, bid, admin_id, [ok_id, bad_id], "activate", dry_run=True).json()
    assert any("בדיקת תקינות" in w for w in prev["warnings"]), prev["warnings"]

    d = _bulk(client, bid, admin_id, [ok_id, bad_id], "activate").json()
    by_id = {r["id"]: r for r in d["results"]}
    assert by_id[ok_id]["ok"] is True and by_id[ok_id]["message"] == "הופעלה"
    assert by_id[bad_id]["ok"] is False and "אינו חבר בלוח" in by_id[bad_id]["message"]
    with Session(cityos_main.engine) as db:
        assert db.query(Automation).filter(Automation.id == ok_id).first().is_active is True
        assert db.query(Automation).filter(Automation.id == bad_id).first().is_active is False


def test_the_health_check_catches_a_status_the_board_no_longer_has(client, admin_id):
    bid = _board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
               status="paused")["id"]
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == aid).first()
        a.config = {"a_status": "no_such_status"}
        db.commit()
    d = _bulk(client, bid, admin_id, [aid], "activate").json()
    assert d["results"][0]["ok"] is False
    assert "אינו קיים בלוח" in d["results"][0]["message"], d["results"][0]


def test_ownership_moves_only_to_an_authorised_manager(client, admin_id, guinea_id, member_id):
    bid = _board(client, admin_id, invite=guinea_id)
    ids = [_add(client, bid, admin_id, name=f"כלל {i}")["id"] for i in range(2)]

    # someone who was never invited to the board
    off = _bulk(client, bid, admin_id, ids, "transfer", owner_id=member_id)
    assert off.status_code == 400 and "הוזמן ללוח" in off.json()["detail"]

    # invited, but not a board admin — said plainly rather than done quietly
    editor = _bulk(client, bid, admin_id, ids, "transfer", owner_id=guinea_id)
    assert editor.status_code == 400 and "מנהל מורשה" in editor.json()["detail"]

    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    d = _bulk(client, bid, admin_id, ids, "transfer", owner_id=guinea_id).json()
    assert d["ok"] == 2 and all(r["message"] == "הבעלות הועברה" for r in d["results"])
    with Session(cityos_main.engine) as db:
        assert all(db.query(Automation).filter(Automation.id == i).first().owner_id == guinea_id
                   for i in ids)


def test_a_bulk_action_is_kept_in_each_rules_versions(client, admin_id):
    bid = _board(client, admin_id)
    aid = _add(client, bid, admin_id, name="כלל")["id"]
    _bulk(client, bid, admin_id, [aid], "pause")
    v = client.get(f"/api/automations/{aid}/versions?user_id={admin_id}").json()["versions"]
    assert v[0]["summary"] == "הושהתה בפעולה מרובה", v[0]


def test_there_is_no_bulk_delete(client, admin_id):
    """Left out of the MVP on purpose: everything else here is reversible, and a
    screenful of checkboxes is the wrong place for a choice that is not."""
    bid = _board(client, admin_id)
    aid = _add(client, bid, admin_id)["id"]
    for name in ("delete", "remove", "purge"):
        r = _bulk(client, bid, admin_id, [aid], name)
        assert r.status_code == 400, f"bulk {name} was accepted"
    assert "delete" not in cityos_main.AUTOMATION_BULK_ACTIONS
    with Session(cityos_main.engine) as db:
        assert db.query(Automation).filter(Automation.id == aid).first() is not None


def test_bulk_needs_a_selection_and_a_board_admin(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id)["id"]
    assert _bulk(client, bid, admin_id, [], "pause").status_code == 400
    assert _bulk(client, bid, guinea_id, [aid], "pause").status_code == 403


def test_bulk_cannot_reach_a_rule_on_another_board(client, admin_id):
    b1, b2 = _board(client, admin_id, "א"), _board(client, admin_id, "ב")
    mine = _add(client, b1, admin_id)["id"]
    theirs = _add(client, b2, admin_id)["id"]
    d = _bulk(client, b1, admin_id, [mine, theirs], "pause").json()
    assert [r["id"] for r in d["results"]] == [mine]
    with Session(cityos_main.engine) as db:
        assert db.query(Automation).filter(Automation.id == theirs).first().is_active is True


def test_activating_under_a_freeze_says_it_will_not_take_effect(client, admin_id):
    bid = _board(client, admin_id)
    aid = _add(client, bid, admin_id, status="paused")["id"]
    f = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "board", "board_id": bid, "reason": "חקירה"}).json()
    d = _bulk(client, bid, admin_id, [aid], "activate", dry_run=True).json()
    assert any("השהיית חירום" in w for w in d["warnings"]), d["warnings"]
    client.post(f"/api/admin/automations/release?user_id={admin_id}",
                json={"freeze_id": f["freeze"]["id"]})


def test_a_board_admin_can_export_their_own_list(client, admin_id, guinea_id, member_id):
    bid = _board(client, admin_id, "לוח ייצוא", invite=guinea_id)
    _add(client, bid, admin_id, name="שורה בייצוא", description="תיאור")
    r = client.get(f"/api/boards/{bid}/automations/export?user_id={admin_id}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    assert "שורה בייצוא" in body and "תיאור" in body
    assert "תיאור עסקי" in body.splitlines()[0]
    # an export is a data permission now, not a viewing one — see the matrix
    assert client.get(f"/api/boards/{bid}/automations/export?user_id={guinea_id}").status_code == 403
    assert client.get(f"/api/boards/{bid}/automations/export?user_id={member_id}").status_code == 403
