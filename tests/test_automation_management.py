"""Group — managing a board's automations (לשונית ניהול).

A rule is not only a recipe, it is an operational object: it has a name and a
business description, an owner distinct from whoever wrote it, a state (draft,
active, paused, suspended by errors, being deleted), an importance, a place in
the running order, and a record of how well it actually works.
"""
from datetime import datetime

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, Notification, Task


def _mk_board(client, admin_id, name="לוח ניהול", invite=None):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    if invite is not None:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": invite, "role": "editor"})
    return bid


def _mk_item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _add(client, bid, admin_id, recipe_id, config, **extra):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config, **extra})


def _list(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()


def test_a_rule_carries_a_name_and_a_business_description(client, admin_id):
    bid = _mk_board(client, admin_id)
    r = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"},
             name="דחיפות לפריט חדש", description="כל קריאה חדשה נכנסת כדחופה עד לסינון")
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["name"] == "דחיפות לפריט חדש"
    assert row["description"].startswith("כל קריאה חדשה")
    assert row["display_name"] == "דחיפות לפריט חדש"


def test_a_rule_without_a_name_is_still_never_nameless(client, admin_id):
    """The sentence stands in for it, so a list row always has a heading."""
    bid = _mk_board(client, admin_id)
    row = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()
    assert row["name"] == "" and row["display_name"]
    assert "«" not in row["display_name"]          # the value markers are for the sentence


def test_a_draft_is_written_but_does_not_run(client, admin_id):
    bid = _mk_board(client, admin_id)
    row = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
               status="draft").json()
    assert row["status"] == "draft" and row["is_active"] is False
    tid = _mk_item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._st_of(t) != "in_progress", "a draft fired"
    # publishing it is a status change like any other
    client.patch(f"/api/automations/{row['id']}?user_id={admin_id}", json={"status": "active"})
    tid2 = _mk_item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid2).first()
        assert cityos_main._st_of(t) == "in_progress"


def test_a_rule_being_deleted_stops_running_without_being_gone(client, admin_id):
    bid = _mk_board(client, admin_id)
    row = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"}).json()
    client.patch(f"/api/automations/{row['id']}?user_id={admin_id}", json={"status": "deleting"})
    tid = _mk_item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._st_of(t) != "in_progress"
    # not in the ordinary list any more — "ההגדרה לא תוצג ברשימה הרגילה" — but
    # kept, and a system admin can still read it for audit
    assert row["id"] not in [a["id"] for a in _list(client, bid, admin_id)["automations"]]
    kept = client.get(f"/api/boards/{bid}/automations"
                      f"?user_id={admin_id}&include_deleting=true").json()["automations"]
    got = next(a for a in kept if a["id"] == row["id"])
    assert got["status"] == "deleting" and got["is_active"] is False


def test_the_old_switch_still_works_and_maps_onto_the_states(client, admin_id):
    """The toggle in the list sends is_active; nothing may have to be rewritten
    for the two fields to agree."""
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]
    off = client.patch(f"/api/automations/{aid}?user_id={admin_id}", json={"is_active": False}).json()
    assert off["status"] == "paused" and off["is_active"] is False
    on = client.patch(f"/api/automations/{aid}?user_id={admin_id}", json={"is_active": True}).json()
    assert on["status"] == "active" and on["is_active"] is True


def test_ownership_is_separate_from_authorship(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]
    row = next(a for a in _list(client, bid, admin_id)["automations"] if a["id"] == aid)
    # nobody named it, so it answers to whoever wrote it
    assert row["owner_id"] == admin_id and row["owner_is_creator"] is True
    row = client.patch(f"/api/automations/{aid}?user_id={admin_id}",
                       json={"owner_id": guinea_id}).json()
    assert row["owner_id"] == guinea_id and row["owner_name"]
    assert row["created_by"] == admin_id, "handing over ownership rewrote history"
    assert row["owner_is_creator"] is False


def test_an_owner_has_to_be_on_the_board(client, admin_id, member_id):
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]
    r = client.patch(f"/api/automations/{aid}?user_id={admin_id}", json={"owner_id": member_id})
    assert r.status_code == 400


def test_importance_is_stored_and_validated(client, admin_id):
    bid = _mk_board(client, admin_id)
    row = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"},
               importance="critical").json()
    assert row["importance"] == "critical"
    assert _add(client, bid, admin_id, "created_set_priority", {"a_priority": "low"},
                importance="somewhat").status_code == 400


def test_the_running_order_decides_who_goes_first(client, admin_id):
    """Two rules on the same event, and the later-written one runs first because
    it was ordered to."""
    bid = _mk_board(client, admin_id)
    first = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
                 run_order=9).json()["id"]
    second = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
                  run_order=1).json()["id"]
    tid = _mk_item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        # run_order 1 set "done" first, then run_order 9 moved it on to "in_progress"
        assert cityos_main._st_of(t) == "in_progress"
    runs = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]
    ordered = [r["automation_id"] for r in reversed(runs) if r["outcome"] == "ran"]
    assert ordered == [second, first], ordered


def test_the_list_counts_what_the_tiles_show(client, admin_id):
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "low"}, status="paused")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "normal"}, status="draft")
    c = _list(client, bid, admin_id)["counts"]
    assert c["total"] == 3 and c["active"] == 1 and c["paused"] == 1 and c["draft"] == 1
    assert c["needs_attention"] == 0


def test_the_filters_are_served_with_the_people_they_name(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    d = _list(client, bid, admin_id)
    ids = {p["id"] for p in d["people"]}
    assert {admin_id, guinea_id} <= ids
    assert "paused_error" in d["statuses"] and "critical" in d["importance"]


def test_a_rule_reports_how_well_it_works(client, admin_id):
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"}).json()["id"]
    row = next(a for a in _list(client, bid, admin_id)["automations"] if a["id"] == aid)
    assert row["success_rate"] is None, "a rate over nothing is unknown, not zero"
    _mk_item(client, bid, admin_id)
    row = next(a for a in _list(client, bid, admin_id)["automations"] if a["id"] == aid)
    assert row["run_count"] == 1 and row["success_rate"] == 100
    assert row["last_run_at"] and row["last_success_at"] and row["last_outcome"] == "ran"


def test_a_skip_is_an_attempt_but_not_a_failure(client, admin_id):
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "due_notify_assignees", {}).json()["id"]
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"due_date": "2026-01-01", "user_id": admin_id})
    # an activation does not reach backwards, so the rule has to have been on
    # before that date arrived
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == aid).first()
        row.activated_at = datetime(2025, 1, 1)
        db.commit()
    client.get(f"/api/boards/{bid}?user_id={admin_id}")          # the date sweep runs on read
    row = next(a for a in _list(client, bid, admin_id)["automations"] if a["id"] == aid)
    assert row["skip_count"] == 1 and row["last_outcome"] == "skipped"
    assert row["fail_count"] == 0 and row["last_run_at"] and not row["last_success_at"]
    assert row["success_rate"] is None, "a skip must not count against the rate"
    assert row["needs_attention"] is False


def test_a_rule_that_keeps_failing_is_taken_out_of_service(client, admin_id, monkeypatch):
    """A rule that cannot work is worse than no rule: it looks configured while
    doing nothing. So it is suspended, and its owner is told."""
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(cityos_main, "_run_action", boom)

    for i in range(cityos_main.AUTOMATION_FAIL_CUTOFF):
        _mk_item(client, bid, admin_id, f"פריט {i}")
    row = next(a for a in _list(client, bid, admin_id)["automations"] if a["id"] == aid)
    assert row["status"] == "paused_error" and row["is_active"] is False
    assert row["needs_attention"] is True
    assert row["fail_count"] == cityos_main.AUTOMATION_FAIL_CUTOFF
    assert row["success_rate"] == 0 and row["last_failure_at"]
    with Session(cityos_main.engine) as db:
        told = db.query(Notification).filter(Notification.user_id == admin_id,
                                             Notification.type == "automation").all()
    assert any("הושהתה" in (n.title or "") for n in told), [n.title for n in told]
    assert _list(client, bid, admin_id)["counts"]["needs_attention"] == 1


def test_reactivating_a_suspended_rule_clears_its_strikes(client, admin_id, monkeypatch):
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(cityos_main, "_run_action", boom)
    for i in range(cityos_main.AUTOMATION_FAIL_CUTOFF):
        _mk_item(client, bid, admin_id, f"פריט {i}")
    monkeypatch.undo()

    row = client.patch(f"/api/automations/{aid}?user_id={admin_id}", json={"status": "active"}).json()
    assert row["status"] == "active" and row["consecutive_failures"] == 0
    # and it is given a fair run again — one failure does not re-suspend it
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == aid).first()
        assert a.is_active is True


def test_only_an_admin_may_manage_the_fields(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]
    for body in ({"name": "שלי"}, {"importance": "critical"}, {"status": "paused"},
                 {"owner_id": guinea_id}, {"run_order": 3}):
        r = client.patch(f"/api/automations/{aid}?user_id={guinea_id}", json=body)
        assert r.status_code == 403, (body, r.status_code)


# ── what the actions menu can do to a rule ──────────────────────────

def test_importance_never_decides_who_runs_first(client, admin_id):
    """The two fields are deliberately independent: importance is for people,
    סדר ביצוע is for the engine."""
    bid = _mk_board(client, admin_id)
    critical = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
                    importance="critical", run_order=8).json()["id"]
    low = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
               importance="low", run_order=2).json()["id"]
    _mk_item(client, bid, admin_id)
    runs = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]
    ordered = [r["automation_id"] for r in reversed(runs) if r["outcome"] == "ran"]
    assert ordered == [low, critical], "importance pushed itself in front of the running order"


def test_a_rule_can_be_duplicated_and_the_copy_does_not_run(client, admin_id):
    bid = _mk_board(client, admin_id)
    src = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
               name="שיוך ראשוני", description="תיאור", importance="high", run_order=4).json()
    r = client.post(f"/api/automations/{src['id']}/duplicate?user_id={admin_id}")
    assert r.status_code == 200, r.text
    copy = r.json()
    assert copy["id"] != src["id"]
    assert copy["name"] == "שיוך ראשוני (עותק)"
    assert copy["description"] == "תיאור" and copy["importance"] == "high"
    assert copy["run_order"] == 4 and copy["config"] == src["config"]
    # a copy that ran the moment it was made would double every action
    assert copy["status"] == "draft" and copy["is_active"] is False
    assert copy["run_count"] == 0 and copy["last_outcome"] == ""


def test_a_copy_of_an_unnamed_rule_still_gets_a_name(client, admin_id):
    bid = _mk_board(client, admin_id)
    src = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()
    copy = client.post(f"/api/automations/{src['id']}/duplicate?user_id={admin_id}").json()
    assert copy["name"].endswith("(עותק)") and len(copy["name"]) > len("(עותק)")


def test_only_an_admin_may_duplicate(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]
    assert client.post(f"/api/automations/{aid}/duplicate?user_id={guinea_id}").status_code == 403


def test_every_change_to_a_rule_becomes_a_version(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"},
               name="התחלה").json()["id"]
    client.patch(f"/api/automations/{aid}?user_id={admin_id}", json={"name": "אחרי שינוי"})
    client.patch(f"/api/automations/{aid}?user_id={admin_id}",
                 json={"importance": "critical", "run_order": 3})
    v = client.get(f"/api/automations/{aid}/versions?user_id={admin_id}").json()["versions"]
    assert [x["version"] for x in v] == [3, 2, 1], "versions are not newest-first"
    assert v[-1]["summary"] == "נוצרה"
    assert "השם" in v[1]["summary"]
    assert "החשיבות" in v[0]["summary"] and "סדר הביצוע" in v[0]["summary"]
    # each version reads on its own, and says who did it
    assert all(x["sentence"] and x["changed_by_name"] for x in v)
    assert v[1]["snapshot"]["name"] == "אחרי שינוי"


def test_a_patch_that_changes_nothing_is_not_a_version(client, admin_id):
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"},
               name="שם").json()["id"]
    client.patch(f"/api/automations/{aid}?user_id={admin_id}", json={"name": "שם"})
    v = client.get(f"/api/automations/{aid}/versions?user_id={admin_id}").json()["versions"]
    assert len(v) == 1


def test_a_duplicate_says_where_it_came_from(client, admin_id):
    bid = _mk_board(client, admin_id)
    src = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()
    copy = client.post(f"/api/automations/{src['id']}/duplicate?user_id={admin_id}").json()
    v = client.get(f"/api/automations/{copy['id']}/versions?user_id={admin_id}").json()["versions"]
    assert v[0]["summary"] == f"שוכפלה מאוטומציה #{src['id']}"


def test_versions_follow_the_automations_permission(client, admin_id, guinea_id, member_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]
    assert client.get(f"/api/automations/{aid}/versions?user_id={admin_id}").status_code == 200
    # a board editor needs the dedicated capability; see test_automations_matrix.py
    assert client.get(f"/api/automations/{aid}/versions?user_id={guinea_id}").status_code == 403
    assert client.get(f"/api/automations/{aid}/versions?user_id={member_id}").status_code == 403


def test_a_dry_run_reports_what_would_happen_and_changes_nothing(client, admin_id):
    """It is worked out, not performed — see tests/test_automations_dryrun.py for
    the whole contract."""
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
               status="draft").json()["id"]
    tid = _mk_item(client, bid, admin_id, "פריט לבדיקה")
    before = client.get(f"/api/tasks/{tid}?user_id={admin_id}").json()

    r = client.post(f"/api/automations/{aid}/test?user_id={admin_id}", json={"task_id": tid})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["verdict"] == "would_run" and d["changed_nothing"] is True
    assert d["notified_nobody"] is True and d["retention_days"] == 30

    after = client.get(f"/api/tasks/{tid}?user_id={admin_id}").json()
    assert after["status"] == before["status"], "the dry run changed the item"
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == aid).first()
        assert (a.run_count or 0) == 0, "a dry run counted as a real run"


def test_a_dry_run_that_would_do_nothing_says_why(client, admin_id):
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"}).json()["id"]
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    d = client.post(f"/api/automations/{aid}/test?user_id={admin_id}",
                    json={"task_id": tid}).json()
    assert d["verdict"] == "would_skip"
    assert any(x["no_op"] and "כבר" in x["note"] for x in d["actions"]), d["actions"]


def test_a_dry_run_is_kept_in_its_own_log_not_the_run_history(client, admin_id):
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
               status="draft").json()["id"]
    tid = _mk_item(client, bid, admin_id)
    client.post(f"/api/automations/{aid}/test?user_id={admin_id}", json={"task_id": tid})
    runs = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]
    assert not [r for r in runs if r["is_test"]], "a test landed in the run history"
    tests = client.get(f"/api/boards/{bid}/automations/tests?user_id={admin_id}").json()
    assert len(tests["tests"]) == 1 and tests["tests"][0]["task_id"] == tid
    assert tests["retention_days"] == 30


def test_a_dry_run_works_on_a_paused_rule(client, admin_id):
    """Checking a rule before switching it on is the main reason to test one."""
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
               status="draft").json()["id"]
    tid = _mk_item(client, bid, admin_id)
    d = client.post(f"/api/automations/{aid}/test?user_id={admin_id}",
                    json={"task_id": tid}).json()
    assert d["verdict"] == "would_run"


def test_a_test_needs_an_item_from_the_same_board(client, admin_id):
    b1, b2 = _mk_board(client, admin_id, "לוח א"), _mk_board(client, admin_id, "לוח ב")
    aid = _add(client, b1, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]
    other = _mk_item(client, b2, admin_id)
    assert client.post(f"/api/automations/{aid}/test?user_id={admin_id}",
                       json={"task_id": other}).status_code == 400
    assert client.post(f"/api/automations/{aid}/test?user_id={admin_id}",
                       json={"task_id": 0}).status_code == 400


def test_only_an_admin_may_test(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]
    tid = _mk_item(client, bid, admin_id)
    assert client.post(f"/api/automations/{aid}/test?user_id={guinea_id}",
                       json={"task_id": tid}).status_code == 403
