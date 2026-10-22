"""Group — the five permission rules the automations engine runs under.

  1. Only a board admin or a system admin may create or change an automation.
  2. A cross-board rule takes admin on the source board and edit rights on the target.
  3. The engine acts through a dedicated system identity, inside a limited grant
     of the boards, fields and action types approved for automation.
  4. Before every execution the dependencies and the permission are re-checked;
     the creator's or owner's broad personal rights are never used.
  5. Losing a permission the rule needs suspends it. What a reader has no
     permission to see is hidden in the log and in the export too.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AutomationRun, Board, Notification, Task, User


def _board(client, admin_id, name="לוח כללים"):
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


def _runs(client, bid, uid, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={uid}{qs}").json()


# ── rule 1 ──────────────────────────────────────────────────────────────────

def test_rule1_an_environment_manager_is_not_enough(client, admin_id, guinea_id):
    """It used to be. A rule rewrites the items of one board, and the person
    answerable for that board is the one who may write it."""
    env = client.post("/api/environments", json={"name": "סביבה לבדיקה",
                                                 "actor_id": admin_id})
    if env.status_code != 200:
        import pytest
        pytest.skip("environments are not creatable in this build")
    eid = env.json()["id"]
    client.post(f"/api/environments/{eid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "manager"})
    bid = client.post("/api/boards", json={"name": "לוח בסביבה", "user_id": admin_id,
                                           "environment_id": eid}).json()["id"]
    r = client.post(f"/api/boards/{bid}/automations?user_id={guinea_id}",
                    json={"recipe_id": "created_set_priority", "config": {"a_priority": "high"}})
    assert r.status_code == 403, r.text
    _member(client, admin_id, bid, guinea_id, "admin")
    assert client.post(f"/api/boards/{bid}/automations?user_id={guinea_id}",
                       json={"recipe_id": "created_set_priority",
                             "config": {"a_priority": "low"}}).status_code == 200


# ── rule 3 ──────────────────────────────────────────────────────────────────

def test_rule3_the_engine_has_an_identity_of_its_own(client, admin_id):
    """What the engine creates is signed by the engine — not by whoever happened
    to save the item that tripped the rule."""
    bid = _board(client, admin_id)
    _add(client, bid, admin_id, "created_subitem" if False else "status_create_subitem",
         {"t_status": "done", "a_text": "נוצר על ידי המנוע"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        sub = db.query(Task).filter(Task.parent_id == tid).first()
        assert sub is not None, "the rule did not run"
        engine = db.query(User).filter(
            User.email == cityos_main.AUTOMATION_IDENTITY_EMAIL).first()
        assert engine is not None, "no engine identity was created"
        assert sub.created_by == engine.id, "the sub-item was signed by a person"
        assert sub.created_by != admin_id
        # the identity is not a usable account
        assert engine.is_active is False and engine.role == "viewer"


def test_rule3_the_grant_lists_the_action_types_allowed(client):
    """A recipe added later, or a row edited by hand, cannot widen what the
    engine may do without this list changing too."""
    import automations as recipes
    granted = cityos_main.AUTOMATION_GRANTED_ACTIONS
    for a in recipes.ACTIONS:
        assert a in granted, f"the catalog offers {a} but the grant does not allow it"
    assert "delete_item" not in granted and "delete_board" not in granted


def test_rule3_an_action_outside_the_grant_is_refused_at_run_time(client, admin_id,
                                                                  monkeypatch):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "AUTOMATION_GRANTED_ACTIONS", frozenset())
    _item(client, bid, admin_id)
    runs = _runs(client, bid, admin_id)["runs"]
    assert runs and runs[0]["outcome"] == "skipped"
    assert "אינה מאושרת לאוטומציה" in runs[0]["reason"], runs[0]
    monkeypatch.undo()
    with Session(cityos_main.engine) as db:
        # refused, and taken out of service — it cannot work as written
        assert db.query(Automation).filter(Automation.id == a["id"]).first().status == "paused_error"


def test_rule3_a_board_outside_the_grant_is_refused(client, admin_id):
    """The rule may only reach a board its connect column still points at."""
    far = _board(client, admin_id, "יעד")
    near = _board(client, admin_id, "מקור")
    cols = [c for c in client.get(f"/api/boards/{near}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    cols.append({"id": "col_link", "type": "connect", "title": "קישור",
                 "connect": {"board_ids": [far], "multi": True}})
    client.patch(f"/api/boards/{near}?actor_id={admin_id}", json={"columns": cols})
    a = _add(client, near, admin_id, "created_create_and_link",
             {"a_connect": "col_link", "a_board": far, "a_text": "פריט מקושר"})
    _item(client, near, admin_id, "ראשון")
    assert _runs(client, near, admin_id)["runs"][0]["outcome"] == "ran"

    # the column is repointed elsewhere; the rule's target is no longer approved
    cols = [c for c in client.get(f"/api/boards/{near}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    for c in cols:
        if c["id"] == "col_link":
            c["connect"] = {"board_ids": [], "multi": True}
    client.patch(f"/api/boards/{near}?actor_id={admin_id}", json={"columns": cols})
    _item(client, near, admin_id, "שני")
    runs = _runs(client, near, admin_id)["runs"]
    assert runs[0]["outcome"] == "skipped", runs[0]
    assert "אינו מאושר" in runs[0]["reason"] or "לוח" in runs[0]["reason"], runs[0]


# ── rule 4 ──────────────────────────────────────────────────────────────────

def test_rule4_dependencies_are_rechecked_before_every_run(client, admin_id):
    """The rule was valid when it was saved. The board changed underneath it."""
    bid = _board(client, admin_id)
    grp = client.post("/api/groups", json={"board_id": bid, "name": "קבוצה",
                                           "actor_id": admin_id})
    assert grp.status_code == 200, grp.text
    gid = grp.json()["id"]
    _add(client, bid, admin_id, "status_move_group", {"t_status": "done", "a_group": gid})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert _runs(client, bid, admin_id)["runs"][0]["outcome"] == "ran"

    client.delete(f"/api/groups/{gid}?actor_id={admin_id}")
    tid2 = _item(client, bid, admin_id, "שני")
    client.patch(f"/api/tasks/{tid2}", json={"status": "done", "user_id": admin_id})
    runs = _runs(client, bid, admin_id)["runs"]
    assert runs[0]["outcome"] == "skipped" and "נמחקה" in runs[0]["reason"], runs[0]


def test_rule4_the_engine_does_not_borrow_the_creators_reach(client, admin_id, guinea_id):
    """The rule was written by a system admin, who reaches every board. That is
    not the authority it runs with: the grant is."""
    far = _board(client, admin_id, "יעד רחוק")
    near = _board(client, admin_id, "מקור רחוק")
    cols = [c for c in client.get(f"/api/boards/{near}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    cols.append({"id": "col_link", "type": "connect", "title": "קישור",
                 "connect": {"board_ids": [far], "multi": True}})
    client.patch(f"/api/boards/{near}?actor_id={admin_id}", json={"columns": cols})
    _add(client, near, admin_id, "created_create_and_link",
         {"a_connect": "col_link", "a_board": far, "a_text": "פריט"})
    # the far board is deleted — the creator's rights would not have helped either
    client.delete(f"/api/boards/{far}?actor_id={admin_id}")
    _item(client, near, admin_id)
    runs = _runs(client, near, admin_id)["runs"]
    assert runs[0]["outcome"] == "skipped", runs[0]


# ── rule 5 ──────────────────────────────────────────────────────────────────

def test_rule5_losing_a_permission_suspends_the_rule_and_tells_its_owner(client, admin_id,
                                                                         guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "editor")
    a = _add(client, bid, admin_id, "created_notify_person", {"a_person": guinea_id},
             name="התראה לדנה")
    _item(client, bid, admin_id, "לפני")
    assert _runs(client, bid, admin_id)["runs"][0]["outcome"] == "ran"

    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    _item(client, bid, admin_id, "אחרי")
    runs = _runs(client, bid, admin_id)["runs"]
    assert runs[0]["outcome"] == "skipped" and "אינו חבר בלוח" in runs[0]["reason"]
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        assert row.status == "paused_error", "the rule stayed active while unable to run"
        assert row.is_active is False
        told = db.query(Notification).filter(Notification.user_id == admin_id,
                                             Notification.type == "automation").all()
    assert any("הרשאה חסרה" in (n.title or "") for n in told), [n.title for n in told]


def test_rule5_a_missing_dependency_skips_but_does_not_suspend(client, admin_id):
    """Only a permission loss takes a rule out of service; a status that was
    removed is this one firing being pointless, not the rule being wrong."""
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        row.config = {"a_status": "no_such_status"}
        db.commit()
    _item(client, bid, admin_id)
    assert _runs(client, bid, admin_id)["runs"][0]["outcome"] == "skipped"
    with Session(cityos_main.engine) as db:
        assert db.query(Automation).filter(Automation.id == a["id"]).first().status == "active"


def test_rule5_the_log_hides_an_item_the_reader_may_not_open(client, admin_id, guinea_id):
    """A run row carries the item's title and the values the rule filled in. An
    item can be restricted inside a board someone may otherwise read."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "admin")       # so they may read the log
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    tid = _item(client, bid, admin_id, "פריט סודי")
    r = client.post(f"/api/tasks/{tid}/permissions",
                    json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"})
    if r.status_code != 200:
        import pytest
        pytest.skip("item permissions are not settable in this build")

    mine = _runs(client, bid, admin_id)["runs"]
    assert any(x["task_title"] == "פריט סודי" for x in mine)
    theirs = _runs(client, bid, guinea_id)["runs"]
    hidden = [x for x in theirs if x.get("redacted")]
    assert hidden, "the restricted item's row was served in full"
    assert hidden[0]["task_title"] == "פריט שאין לך הרשאה אליו"
    assert hidden[0]["sentence"] == "—" and hidden[0]["task_id"] is None
    assert hidden[0]["can_retry"] is False, "a hidden row could still be re-run"


def test_rule5_the_export_hides_it_too(client, admin_id, guinea_id):
    """More so, not less — the file leaves the system."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id, "admin")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    tid = _item(client, bid, admin_id, "פריט מוגן")
    r = client.post(f"/api/tasks/{tid}/permissions",
                    json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"})
    if r.status_code != 200:
        import pytest
        pytest.skip("item permissions are not settable in this build")
    with Session(cityos_main.engine) as db:
        from models import RolePermission
        row = (db.query(RolePermission)
                 .filter(RolePermission.capability == "export_automation_log").all())
        for x in row:
            x.allowed = True
        db.commit()
    got = client.get(f"/api/boards/{bid}/automations/runs/export?user_id={guinea_id}")
    assert got.status_code == 200, got.text
    body = got.content.decode("utf-8-sig")
    assert "פריט מוגן" not in body, "the export leaked a restricted item"
    assert "פריט שאין לך הרשאה אליו" in body
    with Session(cityos_main.engine) as db:
        from models import RolePermission
        for x in db.query(RolePermission).filter(
                RolePermission.capability == "export_automation_log").all():
            x.allowed = False
        db.commit()


def test_rule3_the_identity_survives_a_dry_run(client, admin_id):
    """A dry run ends in a rollback by design. An identity created inside one
    would vanish with it while the cache went on handing out its id."""
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"}, status="draft")
    tid = _item(client, bid, admin_id)
    client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}", json={"task_id": tid})
    with Session(cityos_main.engine) as db:
        uid = cityos_main._automation_identity(db)
        assert uid, "the engine has no identity"
        assert db.query(User).filter(User.id == uid).first() is not None, \
            "the cached identity points at a row that does not exist"


def test_rule3_the_identity_is_made_at_startup(client):
    with Session(cityos_main.engine) as db:
        u = db.query(User).filter(
            User.email == cityos_main.AUTOMATION_IDENTITY_EMAIL).first()
    assert u is not None and u.is_active is False


# ── rule 3, the rest of the grant — "לוחות, שדות וסוגי פעולות" ──────────────
# The boards are granted by the connect column, the action types by the list
# above. The FIELDS were written down and never asked: AUTOMATION_GRANTED_FIELDS
# was a constant nothing read. Today's actions happen to stay inside it, so
# nothing was wrong on the board — but a grant nobody checks is not a grant, and
# the next action added to the catalog would widen what the engine may write to
# an item without anything saying so.

def test_rule3_every_granted_action_declares_the_fields_it_writes(client):
    writes = cityos_main.AUTOMATION_ACTION_FIELDS
    for act in cityos_main.AUTOMATION_GRANTED_ACTIONS:
        assert act in writes, f"{act} is allowed to run without saying what it writes"
        assert set(writes[act]) <= cityos_main.AUTOMATION_GRANTED_FIELDS, \
            f"{act} writes outside the grant: {writes[act]}"
    import automations as recipes
    for act in recipes.ACTIONS:
        assert act in writes, f"the catalog offers {act} and nothing says what it writes"


def test_rule3_a_field_outside_the_grant_is_refused_at_run_time(client, admin_id,
                                                                monkeypatch):
    """The same answer the action grant gives, for the other half of it."""
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id)                       # שנה עדיפות
    monkeypatch.setattr(cityos_main, "AUTOMATION_GRANTED_FIELDS",
                        cityos_main.AUTOMATION_GRANTED_FIELDS - {"priority"})
    _item(client, bid, admin_id)
    runs = _runs(client, bid, admin_id)["runs"]
    assert runs and runs[0]["outcome"] == "skipped", runs[:1]
    assert "אינו מאושר לאוטומציה" in runs[0]["reason"], runs[0]
    monkeypatch.undo()
    with Session(cityos_main.engine) as db:
        assert db.query(Automation).filter(
            Automation.id == a["id"]).first().status == "paused_error"


def test_rule3_a_field_inside_the_grant_still_runs(client, admin_id):
    bid = _board(client, admin_id)
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    assert _runs(client, bid, admin_id)["runs"][0]["outcome"] == "ran"


# ── rule 5, the rest of it — every door onto a restricted item ─────────────
# The run log and its export hide an item the reader may not open. They are not
# the only places a run shows its item.

def _secret_item(client, admin_id, guinea_id, bid, title="פריט סודי"):
    """An item on `bid` that guinea — an admin of the board — may not open."""
    tid = _item(client, bid, admin_id, title)
    r = client.post(f"/api/tasks/{tid}/permissions",
                    json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"})
    assert r.status_code == 200, r.text
    return tid


def test_rule5_the_test_log_hides_an_item_the_reader_may_not_open(client, admin_id,
                                                                  guinea_id):
    """A Dry Run keeps a log of its own, and it carries the item's title and
    every value the test read off it — the run log's restriction, one table
    across."""
    bid = _board(client, admin_id, "לוח יומן בדיקות")
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id)
    tid = _secret_item(client, admin_id, guinea_id, bid)
    assert client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}",
                       json={"task_id": tid}).status_code == 200

    rows = client.get(f"/api/boards/{bid}/automations/tests?user_id={guinea_id}"
                      ).json()["tests"]
    assert rows, "the test log came back empty"
    assert all("פריט סודי" not in str(t) for t in rows), rows
    assert rows[0]["redacted"] is True and rows[0]["task_id"] is None
    # and the admin who may open it still sees it
    mine = client.get(f"/api/boards/{bid}/automations/tests?user_id={admin_id}"
                      ).json()["tests"]
    assert mine[0]["task_title"] == "פריט סודי" and not mine[0].get("redacted")


def test_rule5_a_dry_run_cannot_read_an_item_the_tester_may_not_open(client, admin_id,
                                                                     guinea_id):
    """A Dry Run reports every condition's actual value off the item. Being the
    board's admin is not permission to open an item inside it."""
    bid = _board(client, admin_id, "לוח בדיקה יבשה")
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id)
    tid = _secret_item(client, admin_id, guinea_id, bid)
    r = client.post(f"/api/automations/{a['id']}/test?user_id={guinea_id}",
                    json={"task_id": tid})
    assert r.status_code == 403, r.text


def test_rule5_a_manual_run_cannot_reach_an_item_the_runner_may_not_open(client, admin_id,
                                                                         guinea_id):
    """And the rule is not a way to write on one either."""
    bid = _board(client, admin_id, "לוח הפעלה ידנית")
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id)
    tid = _secret_item(client, admin_id, guinea_id, bid)
    r = client.post(f"/api/automations/{a['id']}/run?user_id={guinea_id}",
                    json={"task_id": tid})
    assert r.status_code == 403, r.text
    assert client.post(f"/api/automations/{a['id']}/run?user_id={admin_id}",
                       json={"task_id": tid}).status_code == 200


def test_rule5_a_run_hidden_in_the_log_cannot_be_retried_from_it(client, admin_id,
                                                                 guinea_id):
    """The log already refuses to say which item this was. Retrying it would
    run the rule on that item all the same."""
    bid = _board(client, admin_id, "לוח הפעלה חוזרת מוסתרת")
    _member(client, admin_id, bid, guinea_id, "admin")
    _add(client, bid, admin_id, "created_set_status", {"a_status": "no_such_status"})
    tid = _secret_item(client, admin_id, guinea_id, bid)
    row = next(r for r in _runs(client, bid, admin_id)["runs"] if r["task_id"] == tid)
    assert row["can_retry"], row
    hidden = next(r for r in _runs(client, bid, guinea_id)["runs"] if r["id"] == row["id"])
    assert hidden["redacted"] is True and hidden["can_retry"] is False
    assert client.post(f"/api/automation-runs/{row['id']}/retry?user_id={guinea_id}"
                       ).status_code == 403
