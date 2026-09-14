"""Group — the automations run history (היסטוריית הפעלות).

Every attempt a rule makes is recorded, including the ones that did nothing: a
rule that fired, a rule that matched but had nothing to do, and a rule that
failed. A skipped or failed attempt can be run again, and the retry is its own
row pointing back at the attempt it replayed.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AutomationRun


def _mk_board(client, admin_id, name="לוח היסטוריה", invite=None):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    if invite is not None:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": invite, "role": "editor"})
    return bid


def _mk_item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _add(client, bid, admin_id, recipe_id, config, active=True):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config, "is_active": active})


def _runs(client, bid, admin_id, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}{qs}").json()


def test_a_rule_that_fires_is_recorded(client, admin_id):
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    tid = _mk_item(client, bid, admin_id, "פריט חדש")
    d = _runs(client, bid, admin_id)
    ran = [r for r in d["runs"] if r["task_id"] == tid]
    assert len(ran) == 1
    row = ran[0]
    assert row["outcome"] == "ran"
    assert row["trigger"] == "item_created" and row["action"] == "set_priority"
    # the row reads on its own — the rule's sentence and the item's title are copied in
    assert "עדיפות" in row["sentence"] and row["task_title"] == "פריט חדש"
    assert d["counts"]["ran"] >= 1


def test_a_rule_with_nothing_to_do_is_recorded_as_a_skip(client, admin_id):
    """The question the history exists to answer is "why did nothing happen?" —
    so a rule that matched and had no work is a row, not silence."""
    bid = _mk_board(client, admin_id)
    # the item is created with no assignees, so "notify the assignees" has nobody
    _add(client, bid, admin_id, "created_notify_person", {"a_person": admin_id})
    _add(client, bid, admin_id, "due_notify_assignees", {})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"due_date": "2020-01-01", "user_id": admin_id})
    client.get(f"/api/boards/{bid}?user_id={admin_id}")        # the date sweep runs on read
    skips = _runs(client, bid, admin_id, outcome="skipped")["runs"]
    assert any(r["action"] == "notify_assignees" and "משויכים" in r["reason"] for r in skips), \
        [(r["action"], r["reason"]) for r in skips]


def test_a_status_rule_skips_when_the_item_is_already_there(client, admin_id):
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "assigned_set_status", {"a_status": "in_progress"})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "in_progress", "user_id": admin_id})
    # assigning now asks for a status the item already has
    client.post(f"/api/tasks/{tid}/assignees", json={"actor_id": admin_id, "user_id": admin_id})
    skips = _runs(client, bid, admin_id, outcome="skipped")["runs"]
    assert any(r["action"] == "set_status" and "כבר" in r["reason"] for r in skips), \
        [(r["action"], r["reason"]) for r in skips]


def test_a_skipped_run_can_be_tried_again(client, admin_id, guinea_id):
    """The skip's cause is fixable — the recipient was not a member — so the
    retry does what the first attempt could not, and both attempts stay."""
    bid = _mk_board(client, admin_id)
    with Session(cityos_main.engine) as db:
        # written straight to the row: the API refuses to SAVE a rule naming a
        # non-member, which is the point — this is the rule going stale later
        db.add(Automation(board_id=bid, recipe_id="created_notify_person",
                          config={"a_person": guinea_id}, is_active=True))
        db.commit()
    _mk_item(client, bid, admin_id)
    skipped = [r for r in _runs(client, bid, admin_id, outcome="skipped")["runs"]
               if r["action"] == "notify_person"]
    assert skipped and skipped[0]["can_retry"]
    rid = skipped[0]["id"]

    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    r = client.post(f"/api/automation-runs/{rid}/retry?user_id={admin_id}")
    assert r.status_code == 200, r.text
    again = r.json()["run"]
    assert again["outcome"] == "ran" and again["is_retry"] and again["retry_of"] == rid

    d = _runs(client, bid, admin_id)
    first = next(x for x in d["runs"] if x["id"] == rid)
    assert first["outcome"] == "skipped" and first["retried_at"], "the first attempt was overwritten"
    assert d["counts"]["retried"] >= 1


def test_a_run_that_worked_is_not_retried(client, admin_id):
    """Replaying it would apply the action a second time."""
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _mk_item(client, bid, admin_id)
    ran = _runs(client, bid, admin_id, outcome="ran")["runs"][0]
    assert not ran["can_retry"]
    assert client.post(f"/api/automation-runs/{ran['id']}/retry?user_id={admin_id}").status_code == 400


def test_only_a_board_admin_may_retry(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _add(client, bid, admin_id, "assigned_set_status", {"a_status": "todo"})
    tid = _mk_item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/assignees", json={"actor_id": admin_id, "user_id": admin_id})
    skipped = _runs(client, bid, admin_id, outcome="skipped")["runs"]
    assert skipped, "expected the todo→todo rule to skip"
    r = client.post(f"/api/automation-runs/{skipped[0]['id']}/retry?user_id={guinea_id}")
    assert r.status_code == 403


def test_the_history_is_readable_by_any_member_and_nobody_else(client, admin_id, guinea_id, member_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    assert client.get(f"/api/boards/{bid}/automations/runs?user_id={guinea_id}").status_code == 200
    assert client.get(f"/api/boards/{bid}/automations/runs?user_id={member_id}").status_code == 403


def test_deleting_a_rule_keeps_its_history(client, admin_id):
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]
    _mk_item(client, bid, admin_id)
    assert _runs(client, bid, admin_id)["counts"]["total"] >= 1
    client.delete(f"/api/automations/{aid}?user_id={admin_id}")
    left = _runs(client, bid, admin_id)["runs"]
    orphan = [r for r in left if r["automation_id"] is None]
    assert orphan, "the rule took its history with it"
    # it still reads without the rule behind it, and cannot be run again
    assert orphan[0]["sentence"] and not orphan[0]["can_retry"]


def test_a_cascade_stopped_by_the_depth_ceiling_says_so(client, admin_id):
    """Two rules pointing at each other stop, and the history records where."""
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "status_set_priority", {"t_status": "in_progress", "a_priority": "high"})
    _add(client, bid, admin_id, "priority_notify_person", {"t_priority": "high", "a_person": admin_id})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "in_progress", "user_id": admin_id})
    d = _runs(client, bid, admin_id)
    assert [r for r in d["runs"] if r["outcome"] == "ran" and r["depth"] == 0]
    assert [r for r in d["runs"] if r["depth"] > 0], "the cascade was not recorded as a cascade"


def test_the_history_is_bounded(client, admin_id, monkeypatch):
    monkeypatch.setattr(cityos_main, "AUTOMATION_RUN_LOG_MAX", 5)
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    for i in range(12):
        _mk_item(client, bid, admin_id, f"פריט {i}")
    with Session(cityos_main.engine) as db:
        cityos_main._prune_automation_runs(db, bid)
        db.commit()
        n = db.query(AutomationRun).filter(AutomationRun.board_id == bid).count()
    assert n <= 5, f"the log kept {n} rows"


def test_the_creation_tab_is_served_both_ways(client, admin_id):
    """The templates, and the same set indexed trigger → action for building one
    from scratch. Both must resolve to a recipe, or the two paths would store
    different things."""
    d = client.get(f"/api/automations/recipes?user_id={admin_id}").json()
    ids = {r["id"] for r in d["recipes"]}
    bp = {b["trigger"]: b for b in d["blueprint"]}
    assert "status_changes_to" in bp and bp["status_changes_to"]["label"].endswith("…")
    for b in d["blueprint"]:
        assert b["actions"], b["trigger"]
        for a in b["actions"]:
            assert a["recipe_id"] in ids
    assert d["triggers"]["item_created"] and d["actions"]["notify_person"]
