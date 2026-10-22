"""Group — הפעלה ידנית ושכפול: two buttons that must not be one.

  · A manual run acts on ONE item, after a preview of exactly what it would do
    and a confirmation of that preview, and is in the log with the identity of
    whoever pressed it.
  · Only a system admin may step over a rule's conditions, after writing a
    reason, which goes to the Audit.
  · A duplicate is a new DRAFT. Whoever asked for it is its creator and its
    owner. Nothing of what the original did comes with it — no runs, no tests,
    no counters, and none of the markers that make a rule skip work it has
    already done.
  · A cross-board reference is copied only where the person copying it has the
    rights that reference takes.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AuditLog, AutomationRun, AutomationTestRun, Task, User


def _board(client, admin_id, name="לוח ידני"):
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


def _run(client, aid, tid, uid, **body):
    return client.post(f"/api/automations/{aid}/run?user_id={uid}",
                       json={"task_id": tid, **body})


def _runs(client, bid, uid):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={uid}").json()["runs"]


def _audit(aid, action):
    with Session(cityos_main.engine) as db:
        return db.query(AuditLog).filter(AuditLog.entity_type == "automation",
                                         AuditLog.entity_id == aid,
                                         AuditLog.action == action).all()


# ── הפעלה ידנית ─────────────────────────────────────────────────────────────

def test_a_manual_run_acts_on_one_item_and_signs_the_log_with_the_person(client, admin_id,
                                                                          guinea_id):
    bid = _board(client, admin_id, "לוח הפעלה ידנית")
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"}, status="paused")
    one, other = _item(client, bid, admin_id, "הפריט"), _item(client, bid, admin_id, "השני")

    r = _run(client, a["id"], one, guinea_id)
    assert r.status_code == 200, r.text
    row = r.json()["run"]
    assert row["outcome"] == "ran" and row["task_id"] == one
    # the person, not the engine: the engine signs what it WRITES, the log says
    # who asked for it
    assert row["actor_id"] == guinea_id and row["actor_name"]
    assert row["is_test"] is False
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == one).first()) == "done"
        assert cityos_main._st_of(db.query(Task).filter(Task.id == other).first()) != "done", \
            "the manual run reached an item nobody picked"


def test_a_manual_run_needs_an_item(client, admin_id):
    bid = _board(client, admin_id, "לוח בלי פריט")
    a = _add(client, bid, admin_id)
    assert client.post(f"/api/automations/{a['id']}/run?user_id={admin_id}",
                       json={}).status_code == 400


def test_the_screen_previews_a_manual_run_before_it_runs_it():
    """The button that runs the rule sits under the Dry Run of the very item it
    would run on — picking from the list only fetches that preview."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
           ).read_text(encoding="utf-8")
    i = src.index("  async runTest(taskId){")
    body = src[i:i + 900]
    assert "'/test'" in body, "picking an item for a manual run does not ask for a preview"
    assert "/run" not in body, "picking an item runs the rule straight away"
    assert "async confirmRun(){" in src and "Automations.confirmRun()" in src
    assert "אישור הפעלה על" in src
    # and the override is offered to a system admin only, with a reason
    assert "st.me&&st.me.role==='admin'" in src
    assert "עקוף את תנאי הכלל" in src and "סיבה לעקיפה" in src


# ── עקיפת תנאים ─────────────────────────────────────────────────────────────

def _conditioned(client, bid, admin_id):
    """A rule that only acts on a critical item — on an item that is not one."""
    a = _add(client, bid, admin_id, "created_set_status",
             {"a_status": "done",
              "conditions": [{"kind": "priority_is", "value": "critical"}]})
    return a, _item(client, bid, admin_id, "פריט רגיל")


def test_without_an_override_the_conditions_hold(client, admin_id):
    bid = _board(client, admin_id, "לוח תנאי")
    a, tid = _conditioned(client, bid, admin_id)
    row = _run(client, a["id"], tid, admin_id).json()["run"]
    assert row["outcome"] == "skipped" and "התנאי" in row["reason"], row


def test_only_a_system_admin_may_step_over_the_conditions(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח עקיפה")
    _member(client, admin_id, bid, guinea_id, "admin")       # admin OF THE BOARD
    a, tid = _conditioned(client, bid, admin_id)
    r = _run(client, a["id"], tid, guinea_id, override=True, reason="סיבה מספיק ארוכה")
    assert r.status_code == 403, r.text
    assert "מנהל מערכת" in r.json()["detail"]
    assert _audit(a["id"], "override_conditions") == []
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) != "done"


def test_an_override_without_a_reason_is_refused(client, admin_id):
    bid = _board(client, admin_id, "לוח בלי סיבה")
    a, tid = _conditioned(client, bid, admin_id)
    for reason in ("", "   ", "קצר"):
        r = _run(client, a["id"], tid, admin_id, override=True, reason=reason)
        assert r.status_code == 400, (reason, r.text)
        assert "סיבה" in r.json()["detail"]
    assert _audit(a["id"], "override_conditions") == []


def test_a_system_admin_with_a_reason_runs_it_and_the_audit_says_so(client, admin_id):
    bid = _board(client, admin_id, "לוח עקיפה מאושרת")
    a, tid = _conditioned(client, bid, admin_id)
    r = _run(client, a["id"], tid, admin_id, override=True,
             reason="הפריט טופל ידנית מול הקבלן")
    assert r.status_code == 200, r.text
    row = r.json()["run"]
    assert row["outcome"] == "ran", row
    # the history can tell this run from an ordinary one
    assert "התנאים נעקפו" in row["reason"] and "הקבלן" in row["reason"], row
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) == "done"
    logs = _audit(a["id"], "override_conditions")
    assert len(logs) == 1, logs
    assert logs[0].new_value == "הפריט טופל ידנית מול הקבלן"
    assert str(tid) in (logs[0].old_value or "")           # which item
    assert logs[0].changed_by == admin_id                  # who
    assert logs[0].created_at is not None                  # and when


def test_an_override_steps_over_conditions_and_over_nothing_else(client, admin_id, guinea_id):
    """A reason typed into a box does not bring back a membership somebody
    revoked, and it does not restore a deleted group."""
    bid = _board(client, admin_id, "לוח עקיפה חסומה")
    _member(client, admin_id, bid, guinea_id, "editor")
    a = _add(client, bid, admin_id, "created_notify_person", {"a_person": guinea_id})
    tid = _item(client, bid, admin_id)
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    r = _run(client, a["id"], tid, admin_id, override=True, reason="צריך לשלוח בכל זאת")
    assert r.status_code == 200, r.text
    assert r.json()["run"]["outcome"] == "skipped", r.json()["run"]
    assert "חבר בלוח" in r.json()["run"]["reason"] or "מושבת" in r.json()["run"]["reason"]


# ── שכפול ───────────────────────────────────────────────────────────────────

def test_a_copy_is_a_draft_owned_by_whoever_asked_for_it(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח שכפול")
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id, name="המקור")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"owner_id": admin_id})
    copy = client.post(f"/api/automations/{a['id']}/duplicate?user_id={guinea_id}")
    assert copy.status_code == 200, copy.text
    c = copy.json()
    assert c["status"] == "draft" and c["is_active"] is False
    assert c["created_by"] == guinea_id, "the copy was signed by the original's author"
    assert c["owner_id"] == guinea_id, "the copy answers to the original's owner"
    assert c["id"] != a["id"] and c["config"] == a["config"]
    # and the original is untouched
    assert client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()["automations"]
    with Session(cityos_main.engine) as db:
        src = db.query(Automation).filter(Automation.id == a["id"]).first()
        assert src.owner_id == admin_id and src.status == "active"


def test_a_copy_brings_none_of_what_the_original_did(client, admin_id):
    bid = _board(client, admin_id, "לוח היסטוריה")
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    tid = _item(client, bid, admin_id)                       # one real run
    client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}",
                json={"task_id": tid})                       # and one test
    with Session(cityos_main.engine) as db:
        src = db.query(Automation).filter(Automation.id == a["id"]).first()
        assert src.run_count >= 1
        src.state = {"fired": [tid], "told": {"loop": "x"}}   # what it has already done
        src.consecutive_failures = 2
        db.commit()

    c = client.post(f"/api/automations/{a['id']}/duplicate?user_id={admin_id}").json()
    with Session(cityos_main.engine) as db:
        copy = db.query(Automation).filter(Automation.id == c["id"]).first()
        assert copy.run_count == 0 and copy.fail_count == 0 and copy.skip_count == 0
        assert copy.consecutive_failures == 0 and copy.last_outcome == ""
        assert copy.last_run_at is None and copy.activated_at is None
        # the idempotency markers — "already fired for this item", "already told
        # the owner" — are the state, and the copy starts with none of it
        assert (copy.state or {}) == {}, copy.state
        assert db.query(AutomationRun).filter(
            AutomationRun.automation_id == copy.id).count() == 0
        assert db.query(AutomationTestRun).filter(
            AutomationTestRun.automation_id == copy.id).count() == 0
        # and the original keeps its own
        assert db.query(AutomationRun).filter(
            AutomationRun.automation_id == a["id"]).count() >= 1


def test_a_copy_starts_its_own_version_history(client, admin_id):
    bid = _board(client, admin_id, "לוח גרסאות עותק")
    a = _add(client, bid, admin_id, name="ראשון")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"name": "שני"})
    c = client.post(f"/api/automations/{a['id']}/duplicate?user_id={admin_id}").json()
    v = client.get(f"/api/automations/{c['id']}/versions?user_id={admin_id}").json()["versions"]
    assert [x["version"] for x in v] == [1], v
    assert f"#{a['id']}" in v[0]["summary"], v[0]["summary"]


def test_copying_twice_makes_two(client, admin_id):
    bid = _board(client, admin_id, "לוח שני עותקים")
    a = _add(client, bid, admin_id)
    one = client.post(f"/api/automations/{a['id']}/duplicate?user_id={admin_id}").json()
    two = client.post(f"/api/automations/{a['id']}/duplicate?user_id={admin_id}").json()
    assert one["id"] != two["id"]
    rows = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()["automations"]
    assert len([x for x in rows if x["id"] in (one["id"], two["id"])]) == 2


def test_a_rule_that_is_not_there_cannot_be_copied(client, admin_id):
    assert client.post(f"/api/automations/{10 ** 7}/duplicate?user_id={admin_id}"
                       ).status_code == 404


def test_only_a_board_admin_may_copy(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח שכפול הרשאות")
    _member(client, admin_id, bid, guinea_id, "editor")
    a = _add(client, bid, admin_id)
    assert client.post(f"/api/automations/{a['id']}/duplicate?user_id={guinea_id}"
                       ).status_code == 403


# ── הפניות חוצות לוחות בעותק ────────────────────────────────────────────────

def _connect_board(client, admin_id, name, targets):
    bid = _board(client, admin_id, name)
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    cols.append({"id": "col_link", "type": "connect", "title": "קישור",
                 "connect": {"board_ids": targets, "multi": True}})
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    assert r.status_code == 200, r.text
    return bid


def test_an_extra_action_reaching_a_board_they_lack_is_dropped_whole(client, admin_id,
                                                                     guinea_id):
    """The rest of the rule survives — losing four actions over one reference
    would be a strange way to enforce a permission — and half an action is not
    copied, because half an action is one nobody wrote."""
    far = _board(client, admin_id, "לוח רחוק לפעולה")
    near = _connect_board(client, admin_id, "לוח קרוב לפעולה", [far])
    a = _add(client, near, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "create_and_link",
                           "values": {"connect": "col_link", "board": far,
                                      "text": "פריט מרוחק"}}]})
    _member(client, admin_id, near, guinea_id, "admin")
    c = client.post(f"/api/automations/{a['id']}/duplicate?user_id={guinea_id}")
    assert c.status_code == 200, c.text
    got = c.json()
    assert got["config"]["a_priority"] == "high", "the rest of the rule went with it"
    assert not got["config"].get("actions"), got["config"]
    assert any("לוח רחוק לפעולה" in x for x in got["dropped_references"]), got
    # and nothing half-written was left behind
    assert got["status"] == "draft"


def test_a_copy_inside_one_board_carries_everything(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח בלי חוץ")
    _member(client, admin_id, bid, guinea_id, "admin")
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "notify_assignees", "values": {}}]})
    c = client.post(f"/api/automations/{a['id']}/duplicate?user_id={guinea_id}").json()
    assert c["config"] == a["config"] and c["dropped_references"] == []
