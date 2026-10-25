"""סעיף 17.4 — הודעות המערכת: חמישה נוסחים, כל אחד במקום שלו.

The five sentences were written down in 17.3 and served on the row. Nothing
displayed them, and one of them was wrong in a way only showing it reveals:
"האוטומציה נשמרה והופעלה. היא תחול על אירועים חדשים מעכשיו" came back for
EVERY active rule, including one that has been running since March. That is
not a state, it is a moment — and a sentence about a moment, repeated as a
state, is a screen telling a person something untrue every time they open it.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, Task

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, uid, name):
    return client.post("/api/boards", json={"name": name, "user_id": uid}).json()["id"]


def _item(client, bid, uid, title="פריט", **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": uid, **kw}).json()["id"]


def _add(client, bid, uid, recipe_id="created_set_priority", config=None, **extra):
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": uid, "recipe_id": recipe_id,
                          "config": config or {"a_priority": "high"}, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _row(client, bid, uid, rid):
    return next(x for x in client.get(f"/api/boards/{bid}/automations?user_id={uid}"
                                      ).json()["automations"] if x["id"] == rid)


def _col(client, bid, uid, **spec):
    cols = client.get(f"/api/boards/{bid}").json()["columns"]
    col = {"id": spec.pop("id", "col_x"), **spec}
    client.patch(f"/api/boards/{bid}", json={"actor_id": uid, "columns": cols + [col]})
    return col


def _runs(client, bid, uid):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={uid}"
                      ).json()["runs"]


# ── הנוסח מתאים לתוצאה בפועל ──────────────────────────────────────────────

def test_activation_is_said_once_at_the_moment_and_not_forever(client, admin_id):
    """It is a moment, not a state. Said in the answer to the call that did
    it, and absent from every read afterwards."""
    bid = _board(client, admin_id, "הודעות הפעלה")
    a = _add(client, bid, admin_id, status="draft")
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                     json={"status": "active"})
    assert r.status_code == 200, r.text
    assert r.json()["said"] == cityos_main.AUTOMATION_SAY["activated"], r.json().get("said")
    later = _row(client, bid, admin_id, a["id"])
    assert later["status"] == "active"
    assert not later.get("say"), \
        f"a rule running for a month still says it was just switched on: {later.get('say')}"
    assert not later.get("said")


def test_a_rule_created_active_says_it_once_too(client, admin_id):
    bid = _board(client, admin_id, "הודעות יצירה")
    a = _add(client, bid, admin_id)
    assert a["said"] == cityos_main.AUTOMATION_SAY["activated"], a.get("said")
    assert not _row(client, bid, admin_id, a["id"]).get("say")


def test_a_draft_is_told_nothing(client, admin_id):
    bid = _board(client, admin_id, "הודעות טיוטה")
    a = _add(client, bid, admin_id, status="draft")
    assert not a.get("said"), a.get("said")
    assert not _row(client, bid, admin_id, a["id"]).get("say")


def test_a_missing_dependency_says_the_dependency_sentence(client, admin_id):
    bid = _board(client, admin_id, "הודעות תלות")
    col = _col(client, bid, admin_id, type="text", title="אזור")
    rule = _add(client, bid, admin_id, "column_changed_notify_assignees",
                {"t_column": col["id"]})
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id,
                       "columns": [c for c in client.get(f"/api/boards/{bid}").json()["columns"]
                                   if c["id"] != col["id"]]})
    row = _row(client, bid, admin_id, rule["id"])
    assert row["say"] == cityos_main.AUTOMATION_SAY["dependency"], row.get("say")
    assert row["say_kind"] == "dependency"


def test_a_missing_permission_says_the_permission_sentence(client, admin_id):
    a = _board(client, admin_id, "מקור הרשאה")
    b = _board(client, admin_id, "יעד הרשאה")
    cols = client.get(f"/api/boards/{a}").json()["columns"] + [
        {"type": "connect", "title": "קישור",
         "connect": {"board_ids": [b], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in client.get(f"/api/boards/{a}").json()["columns"]
             if x["type"] == "connect")
    rule = _add(client, a, admin_id, "created_create_and_link",
                {"a_connect": c["id"], "a_board": b, "a_text": "חדש"})
    other = _board(client, admin_id, "יעד אחר הרשאה")
    client.patch(f"/api/boards/{a}",
                 json={"actor_id": admin_id,
                       "columns": [dict(x, connect={**x["connect"], "board_ids": [other]})
                                   if x["id"] == c["id"] else x
                                   for x in client.get(f"/api/boards/{a}").json()["columns"]]})
    _item(client, a, admin_id, "מפעיל")
    row = _row(client, a, admin_id, rule["id"])
    assert row["say"] == cityos_main.AUTOMATION_SAY["permission"], row.get("say")
    assert row["say_kind"] == "permission"


def test_a_loop_says_the_loop_sentence(client, admin_id):
    bid = _board(client, admin_id, "הודעות לולאה")
    rule = _add(client, bid, admin_id, "status_set_priority",
                {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    for _ in range(cityos_main.AUTOMATION_FAIL_CUTOFF):
        with Session(cityos_main.engine) as db:
            t = db.query(Task).filter(Task.id == tid).first()
            cityos_main._run_automations(
                db, t, cityos_main._event("status_changes_to", "item", status="done",
                                          chain_runs=cityos_main.AUTOMATION_CHAIN_MAX_RUNS),
                admin_id)
            db.commit()
    row = _row(client, bid, admin_id, rule["id"])
    assert row["say"] == cityos_main.AUTOMATION_SAY["loop"], row.get("say")
    assert row["say_kind"] == "loop"


def test_a_condition_that_did_not_hold_says_so_on_the_run(client, admin_id):
    bid = _board(client, admin_id, "הודעות תנאי")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "conditions": [{"kind": "has_assignee", "value": True}]})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    r = _runs(client, bid, admin_id)[0]
    assert r["say"] == cityos_main.AUTOMATION_SAY["condition"], r.get("say")
    assert r["say_kind"] == "condition"


def test_a_run_that_worked_says_nothing(client, admin_id):
    """A standard sentence on a row that went fine is noise on every line."""
    bid = _board(client, admin_id, "הודעות הצלחה")
    _add(client, bid, admin_id)
    _item(client, bid, admin_id)
    r = _runs(client, bid, admin_id)[0]
    assert r["status"] == "succeeded" and not r.get("say"), r.get("say")


# ── הקישור ללוג ───────────────────────────────────────────────────────────

def test_the_loop_message_links_to_the_log_it_promises(client, admin_id):
    """«פרטים זמינים בלוג» is a promise the sentence makes; a message that
    makes it without a way there is a message that cannot be acted on."""
    bid = _board(client, admin_id, "הודעות קישור")
    rule = _add(client, bid, admin_id, "status_set_priority",
                {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)
    for _ in range(cityos_main.AUTOMATION_FAIL_CUTOFF):
        with Session(cityos_main.engine) as db:
            t = db.query(Task).filter(Task.id == tid).first()
            cityos_main._run_automations(
                db, t, cityos_main._event("status_changes_to", "item", status="done",
                                          chain_runs=cityos_main.AUTOMATION_CHAIN_MAX_RUNS),
                admin_id)
            db.commit()
    row = _row(client, bid, admin_id, rule["id"])
    assert row["say_log"] is True, row
    assert str(rule["id"]) in (row.get("say_link") or ""), row.get("say_link")


def test_a_reader_who_may_not_open_the_log_is_not_sent_there(client, admin_id,
                                                             member_id):
    bid = _board(client, admin_id, "הודעות הרשאת לוג")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    col = _col(client, bid, admin_id, type="text", title="אזור")
    rule = _add(client, bid, admin_id, "column_changed_notify_assignees",
                {"t_column": col["id"]})
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id,
                       "columns": [c for c in client.get(f"/api/boards/{bid}").json()["columns"]
                                   if c["id"] != col["id"]]})
    r = client.get(f"/api/boards/{bid}/automations?user_id={member_id}")
    if r.status_code == 403:
        return                      # they cannot reach the screen at all
    row = next(x for x in r.json()["automations"] if x["id"] == rule["id"])
    assert row.get("say_log") is False, row
    assert not row.get("say_link"), row


# ── המסך ──────────────────────────────────────────────────────────────────

def test_the_screen_shows_the_message_accessibly(client):
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "frontend" / "index.html").read_text(encoding="utf-8")
    i = src.index("  sayHTML(")
    body = src[i:src.index("\n  },", i)]
    assert 'role="status"' in body, "the message is not announced"
    assert 'dir="auto"' in body, "mixed Hebrew and Latin would flip the line"
    assert "esc(" in body, "a message is rendered as markup"
    assert "say_log" in body and "say_link" in body, "the link is not conditional"
