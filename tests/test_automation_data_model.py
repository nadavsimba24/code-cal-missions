"""סעיף 17.1 — מודל הנתונים: שש הישויות, ומה הן מצביעות עליו.

Three of the six were already here under names this build gave them before
the section named them, and renaming a live table is not a thing to do for a
word: `AutomationExecution` is `automation_runs` and
`AutomationScheduledExecution` is `automation_queue`, aliased so the spec's
name resolves to the same rows.

Two were genuinely absent. An action's own execution lived as JSON inside the
run that contained it — readable by the one screen that knew the shape, and
queryable by nothing: "which action fails most often across the board" had no
answer. And the authorization grant was not data at all; it was a constant in
the source, which means it could be read and never revoked.

And the rule underneath all of it: everything points at an ID. A board, a
column, a group, a status, an item — a reference by name is a reference that
silently moves to a different thing when somebody renames something.
"""
import inspect

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
import main as cityos_main
import models as M

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


def _cols(model):
    return {c.key for c in sa_inspect(model).columns}


# ── שש הישויות ─────────────────────────────────────────────────────────────

def test_all_six_entities_resolve(client):
    for name in ("Automation", "AutomationVersion", "AutomationExecution",
                 "AutomationActionExecution", "AutomationAuthorizationGrant",
                 "AutomationScheduledExecution"):
        assert hasattr(M, name), name
        assert inspect.isclass(getattr(M, name)), name


def test_the_two_aliases_are_the_same_rows_and_not_a_copy(client):
    """Renaming a live table for a word is how a migration loses data. The
    spec's name resolves to the table that already holds these rows."""
    assert M.AutomationExecution is M.AutomationRun
    assert M.AutomationScheduledExecution is M.AutomationQueue


def test_every_entity_has_its_own_table(client):
    seen = {}
    for name in ("Automation", "AutomationVersion", "AutomationExecution",
                 "AutomationActionExecution", "AutomationAuthorizationGrant",
                 "AutomationScheduledExecution"):
        t = getattr(M, name).__tablename__
        assert t not in seen or seen[t] == name or name in ("AutomationExecution",
                                                            "AutomationScheduledExecution")
        seen.setdefault(t, name)
    assert M.AutomationActionExecution.__tablename__ == "automation_action_executions"
    assert M.AutomationAuthorizationGrant.__tablename__ == "automation_grants"


# ── הקשרים בין הישויות ─────────────────────────────────────────────────────

def test_each_entity_points_back_at_the_rule_and_the_board(client):
    for name in ("AutomationVersion", "AutomationExecution",
                 "AutomationActionExecution", "AutomationAuthorizationGrant",
                 "AutomationScheduledExecution"):
        cols = _cols(getattr(M, name))
        assert "automation_id" in cols, (name, sorted(cols))
        assert "board_id" in cols, (name, sorted(cols))


def test_an_action_execution_belongs_to_one_run(client):
    cols = _cols(M.AutomationActionExecution)
    for want in ("run_id", "action_index", "action_key", "status",
                 "idempotency_key", "input", "target", "output",
                 "started_at", "finished_at", "error_code", "error"):
        assert want in cols, (want, sorted(cols))
    fks = {c.key: [str(f.column) for f in c.foreign_keys]
           for c in sa_inspect(M.AutomationActionExecution).columns}
    assert any("automation_runs.id" in x for x in fks["run_id"]), fks["run_id"]


def test_a_grant_says_what_it_covers_and_whether_it_still_holds(client):
    cols = _cols(M.AutomationAuthorizationGrant)
    for want in ("target_board_id", "action_key", "fields", "granted_by",
                 "granted_at", "revoked_at", "revoked_by"):
        assert want in cols, (want, sorted(cols))


# ── הכול לפי מזהים, לעולם לא לפי שמות ─────────────────────────────────────

def test_no_entity_stores_a_reference_by_name(client):
    """A column called board_name or group_title would be a reference that
    silently moves to a different thing the moment somebody renames one."""
    bad = []
    for name in ("Automation", "AutomationVersion", "AutomationExecution",
                 "AutomationActionExecution", "AutomationAuthorizationGrant",
                 "AutomationScheduledExecution"):
        for c in _cols(getattr(M, name)):
            if c.endswith(("_name", "_title", "_label")) and not c.startswith("task_"):
                bad.append(f"{name}.{c}")
    # task_title is the exception and is a COPY, not a reference: the history
    # has to still read after the item is renamed or deleted
    assert bad == [], bad


def test_the_stored_rule_points_at_ids(client, admin_id):
    bid = _board(client, admin_id, "לוח מזהים")
    gid = client.get(f"/api/boards/{bid}").json()["groups"][0]["id"]
    cols = client.get(f"/api/boards/{bid}").json()["columns"]
    col = {"id": "col_zone", "type": "text", "title": "אזור"}
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols + [col]})
    a = _add(client, bid, admin_id, "moved_group_set_status",
             {"t_group": gid, "a_status": "done",
              "conditions": [{"kind": "column_is",
                              "value": {"col": "col_zone", "type": "text",
                                        "value": "צפון"}}]})
    with Session(cityos_main.engine) as db:
        cfg = db.query(M.Automation).filter(M.Automation.id == a["id"]).first().config
    assert cfg["t_group"] == gid and isinstance(cfg["t_group"], int), cfg
    assert cfg[recipes_key()][0]["value"]["col"] == "col_zone", cfg
    # the column's TITLE is nowhere in the stored rule
    assert "אזור" not in str(cfg), cfg
    assert "done" == cfg["a_status"], "a status is stored as its key"


def recipes_key():
    import automations as recipes
    return recipes.CONDITION_KEY


def test_renaming_the_thing_does_not_touch_the_rule(client, admin_id):
    bid = _board(client, admin_id, "לוח שינוי שם מזהים")
    cols = client.get(f"/api/boards/{bid}").json()["columns"]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id,
                                             "columns": cols + [{"id": "col_x",
                                                                 "type": "text",
                                                                 "title": "לפני"}]})
    a = _add(client, bid, admin_id, "column_changed_notify_assignees",
             {"t_column": "col_x"})
    now = client.get(f"/api/boards/{bid}").json()["columns"]
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id,
                       "columns": [dict(c, title="אחרי") if c["id"] == "col_x" else c
                                   for c in now]})
    with Session(cityos_main.engine) as db:
        row = db.query(M.Automation).filter(M.Automation.id == a["id"]).first()
        assert (row.config or {})["t_column"] == "col_x"
        assert row.status == "active", "a rename broke the rule"


# ── מה נכתב בפועל ─────────────────────────────────────────────────────────

def test_a_run_writes_a_row_per_action(client, admin_id):
    bid = _board(client, admin_id, "לוח פעולות כשורות")
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "post_update", "values": {"text": "שלב שני"}}]})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        rows = (db.query(M.AutomationActionExecution)
                  .filter(M.AutomationActionExecution.task_id == tid)
                  .order_by(M.AutomationActionExecution.action_index).all())
    assert [r.action_key for r in rows] == ["set_priority", "post_update"], \
        [r.action_key for r in rows]
    assert [r.action_index for r in rows] == [1, 2]
    assert all(r.status == "succeeded" for r in rows), [r.status for r in rows]
    assert all(r.automation_id == a["id"] and r.board_id == bid for r in rows)
    assert all(r.idempotency_key for r in rows)
    assert len({r.idempotency_key for r in rows}) == 2


def test_an_action_that_failed_says_so_on_its_own_row(client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "לוח פעולה שנכשלה")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})

    def boom(*a, **kw):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(cityos_main, "_apply_priority_key", boom)
    tid = _item(client, bid, admin_id)
    monkeypatch.undo()
    with Session(cityos_main.engine) as db:
        rows = (db.query(M.AutomationActionExecution)
                  .filter(M.AutomationActionExecution.task_id == tid).all())
    assert rows and rows[0].status == "failed_temporary", [r.status for r in rows]
    assert rows[0].error_code == "RuntimeError", rows[0].error_code
    assert "locked" in (rows[0].error or ""), rows[0].error


def test_the_rows_are_queryable_across_boards(client, admin_id):
    """The whole reason this is a table and not JSON inside a run: "which
    action fails most often" is a question somebody asks across boards."""
    with Session(cityos_main.engine) as db:
        from sqlalchemy import func
        rows = (db.query(M.AutomationActionExecution.action_key,
                         func.count(M.AutomationActionExecution.id))
                  .group_by(M.AutomationActionExecution.action_key).all())
    assert rows, "nothing to group"


def test_the_json_steps_are_still_there_for_the_screen(client, admin_id):
    """Backward compatibility: the log screen reads result.steps, and the
    table is written beside it rather than instead of it."""
    bid = _board(client, admin_id, "לוח תאימות")
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    run = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}"
                     ).json()["runs"][0]
    assert ((run["result"] or {}).get("steps") or []), run["result"]


# ── המענק ─────────────────────────────────────────────────────────────────

def _two_boards(client, admin_id, tag):
    a = _board(client, admin_id, f"מקור {tag}")
    b = _board(client, admin_id, f"יעד {tag}")
    cols = client.get(f"/api/boards/{a}").json()["columns"] + [
        {"type": "connect", "title": "קישור",
         "connect": {"board_ids": [b], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in client.get(f"/api/boards/{a}").json()["columns"]
             if x["type"] == "connect")
    return a, b, c


def test_a_cross_board_rule_records_the_grant_it_holds(client, admin_id):
    a, b, c = _two_boards(client, admin_id, "מענק")
    rule = _add(client, a, admin_id, "created_create_and_link",
                {"a_connect": c["id"], "a_board": b, "a_text": "חדש"})
    with Session(cityos_main.engine) as db:
        g = (db.query(M.AutomationAuthorizationGrant)
               .filter(M.AutomationAuthorizationGrant.automation_id == rule["id"]).all())
    assert g, "a rule that writes on another board recorded no grant"
    assert g[0].target_board_id == b and g[0].board_id == a
    assert g[0].action_key == "create_and_link"
    assert g[0].granted_by == admin_id and g[0].revoked_at is None


def test_a_rule_on_its_own_board_needs_no_grant(client, admin_id):
    bid = _board(client, admin_id, "לוח ללא מענק")
    rule = _add(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        assert not (db.query(M.AutomationAuthorizationGrant)
                      .filter(M.AutomationAuthorizationGrant.automation_id
                              == rule["id"]).all())


def test_revoking_the_grant_stops_the_rule(client, admin_id):
    """What makes it data rather than a note: a constant in the source can be
    read and never withdrawn."""
    a, b, c = _two_boards(client, admin_id, "ביטול מענק")
    rule = _add(client, a, admin_id, "created_create_and_link",
                {"a_connect": c["id"], "a_board": b, "a_text": "חדש"})
    _item(client, a, admin_id, "לפני")
    with Session(cityos_main.engine) as db:
        made = db.query(M.Task).filter(M.Task.board_id == b).count()
    assert made >= 1, "it never worked to begin with"
    with Session(cityos_main.engine) as db:
        from datetime import datetime, timezone
        for g in (db.query(M.AutomationAuthorizationGrant)
                    .filter(M.AutomationAuthorizationGrant.automation_id == rule["id"]).all()):
            g.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            g.revoked_by = admin_id
        db.commit()
    _item(client, a, admin_id, "אחרי")
    with Session(cityos_main.engine) as db:
        assert db.query(M.Task).filter(M.Task.board_id == b).count() == made, \
            "a revoked grant still wrote on the other board"
        row = db.query(M.Automation).filter(M.Automation.id == rule["id"]).first()
    assert row.status == "paused_error", row.status


def test_the_tables_exist_in_the_database_and_not_only_in_the_model(client):
    from sqlalchemy import inspect as sai
    names = set(sai(cityos_main.engine).get_table_names())
    assert "automation_action_executions" in names, sorted(n for n in names
                                                           if n.startswith("automation"))
    assert "automation_grants" in names
