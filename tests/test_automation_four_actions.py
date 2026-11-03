"""כלל אחד שעושה עד עשרה דברים — the "אז" with more than one action in it.

A recipe pairs one trigger with one action, and that single action was the
whole "then". Several things that have to happen on one event — assign somebody, raise the
priority, move the item, tell a person — were that many rules listening to the
same trigger: that many rows to write, that many to keep in step when the
status they all watch is renamed, that many lines in the history for one event,
and no order between them beyond run_order.

So a rule may carry up to `MAX_ACTIONS` actions, run in order, under the rule's
own conditions — the conditions belong to the rule, not to each action. The
recipe's own action is the first of them and is stored exactly where it always
was; the extra ones live in `config["actions"]`, beside the conditions, so
drafts, versions, publishing, comparing and the export carry them without
learning a new field.

Three things this group is really about, because each one is a way the feature
could be worse than the four rules it replaces:
  · all four run, in the order written, on one event;
  · a rule that fails halfway leaves nothing behind (a savepoint per rule) —
    "half of it happened" is the hardest thing to work out afterwards;
  · the history says which of them did nothing, instead of reporting the rule
    as a whole and leaving the reader to guess.
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import automations as recipes
import main as cityos_main
from models import Notification, Task

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _board(client, admin_id, name="לוח ארבע פעולות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _member(client, admin_id, bid, uid, role="editor"):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    assert r.status_code == 200, r.text


def _add(client, bid, admin_id, recipe_id, config, **extra):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config, **extra})


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _get(client, bid, aid, admin_id):
    d = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
    return next(a for a in d["automations"] if a["id"] == aid)


def _groups(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["groups"]


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]


def _task(tid):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        return {"status": cityos_main._task_status_key(t),
                "priority": cityos_main._task_priority_key(t),
                "group_id": t.group_id,
                "assignees": sorted(u.id for u in t.assignees)}


# ── all four, on one event, in the order they were written ──────────────────

def test_one_event_runs_all_four_actions(client, admin_id, guinea_id):
    """The report: four rules became one. The rule's own action is the first,
    and the three extras run after it in the order they are listed."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    other = _groups(client, bid, admin_id)[-1]
    r = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "set_status", "values": {"status": "in_progress"}},
                          {"key": "assign_person", "values": {"person": guinea_id}},
                          {"key": "move_to_group", "values": {"group": other["id"]}}]})
    assert r.status_code == 200, r.text

    tid = _item(client, bid, admin_id)
    t = _task(tid)
    assert t["priority"] == "high", "the recipe's own action did not run"
    assert t["status"] == "in_progress", "the second action did not run"
    assert t["assignees"] == [guinea_id], "the third action did not run"
    assert t["group_id"] == other["id"], "the fourth action did not run"


def test_the_whole_rule_is_one_line_in_the_history(client, admin_id, guinea_id):
    """Four rules wrote four rows for one event. One rule writes one."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "set_status", "values": {"status": "in_progress"}},
                      {"key": "notify_person", "values": {"person": guinea_id}}]})
    _item(client, bid, admin_id)
    runs = _runs(client, bid, admin_id)
    assert len(runs) == 1, runs
    assert runs[0]["outcome"] == "ran"


def test_the_sentence_reads_every_action(client, admin_id, guinea_id):
    """The sentence is what the list, the log and the notifications quote. A
    rule that does four things and says one is a rule nobody can audit."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "set_status", "values": {"status": "in_progress"}},
                          {"key": "notify_person", "values": {"person": guinea_id}}]}).json()
    name = client.get("/api/users").json()
    guinea_name = next(u["name"] for u in name if u["id"] == guinea_id)
    s = a["sentence"]
    assert s.count("וגם") == 2, s
    assert "שנה את הסטטוס" in s and guinea_name in s, s
    assert len(a["action_phrases"]) == 2, a["action_phrases"]


def test_the_extra_actions_come_back_as_they_were_stored(client, admin_id, guinea_id):
    """The UI edits what is stored and shows what is rendered — the same
    pairing the conditions have."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "notify_person", "values": {"person": guinea_id}}]}).json()
    # A recipient is stored as what KIND of recipient it is — a fixed person is
    # one of five, and the other four are read off the event (see
    # automations.RECIPIENTS). A bare id is the old shape and still means the
    # one it always meant, normalised on the way in.
    assert a["actions"] == [{"key": "notify_person",
                             "values": {"person": {"kind": "user", "value": guinea_id}}}]
    assert _get(client, bid, a["id"], admin_id)["actions"] == a["actions"]


# ── how many, and which combinations make sense ─────────────────────────────

def test_one_action_past_the_ceiling_is_refused(client, admin_id):
    """The ceiling moved from four to ten; what has not moved is that there is
    one, and that the rule's own action counts towards it."""
    bid = _board(client, admin_id)
    extras = [{"key": "create_subitem", "values": {"text": f"תת {i}"}}
              for i in range(recipes.MAX_ACTIONS)]          # + the recipe's own = one too many
    r = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high", "actions": extras})
    assert r.status_code == 400, r.text
    assert str(recipes.MAX_ACTIONS) in r.json()["detail"]


def test_a_rule_may_carry_ten_actions(client, admin_id):
    bid = _board(client, admin_id)
    extras = [{"key": "create_subitem", "values": {"text": f"תת {i}"}}
              for i in range(recipes.MAX_ACTIONS - 1)]      # + the recipe's own = ten
    r = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high", "actions": extras})
    assert r.status_code == 200, r.text
    assert len(r.json()["actions"]) == recipes.MAX_ACTIONS - 1


def test_four_is_allowed(client, admin_id):
    """The boundary the line above is drawn at, from the other side."""
    bid = _board(client, admin_id)
    other = _groups(client, bid, admin_id)[-1]
    r = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "set_status", "values": {"status": "in_progress"}},
                          {"key": "move_to_group", "values": {"group": other["id"]}},
                          {"key": "create_subitem", "values": {"text": "א"}}]})
    assert r.status_code == 200, r.text


def test_two_actions_writing_the_same_field_are_refused(client, admin_id):
    """The second would overwrite the first, which makes the first a line
    somebody will read as doing something."""
    bid = _board(client, admin_id)
    r = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "set_status", "values": {"status": "in_progress"}},
                          {"key": "set_status", "values": {"status": "done"}}]})
    assert r.status_code == 400, r.text
    assert "פעם אחת" in r.json()["detail"]


def test_an_extra_action_cannot_repeat_the_recipes_own(client, admin_id):
    """The recipe's action is the first action, not a different kind of thing."""
    bid = _board(client, admin_id)
    r = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "set_priority", "values": {"priority": "low"}}]})
    assert r.status_code == 400, r.text


def test_two_notifications_to_two_people_are_fine(client, admin_id, guinea_id):
    """Not every repeat is a contradiction: telling two people is two actions,
    and the one-per-rule limit is only for actions that write one field."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    r = _add(client, bid, admin_id, "created_notify_person",
             {"a_person": admin_id,
              "actions": [{"key": "notify_person", "values": {"person": guinea_id}}]})
    assert r.status_code == 200, r.text
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        told = {n.user_id for n in db.query(Notification)
                .filter(Notification.task_id == tid,
                        Notification.type == "automation").all()}
    assert told == {admin_id, guinea_id}, told


def test_the_same_action_with_the_same_values_is_not_stored_twice(client, admin_id, guinea_id):
    """Doing it twice does it once — the conditions dedupe the same way."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "notify_person", "values": {"person": guinea_id}},
                          {"key": "notify_person", "values": {"person": guinea_id}}]}).json()
    assert len(a["actions"]) == 1, a["actions"]


# ── a blank in an extra action ──────────────────────────────────────────────

def test_a_draft_may_hold_an_unfinished_extra_action(client, admin_id):
    """Exactly what a recipe placeholder may be: a blank somebody comes back
    to. The name says which action is waiting, because four actions can want
    four different people."""
    bid = _board(client, admin_id)
    r = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "notify_person", "values": {}}]}, status="draft")
    assert r.status_code == 200, r.text
    assert r.json()["missing_fields"] == ["נמען (פעולה 2)"], r.json()["missing_fields"]


def test_that_draft_refuses_to_be_switched_on(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "notify_person", "values": {}}]}, status="draft").json()
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "active"})
    assert r.status_code == 400, r.text


def test_an_active_rule_cannot_be_saved_with_a_blank_action(client, admin_id):
    bid = _board(client, admin_id)
    r = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high", "actions": [{"key": "notify_person", "values": {}}]})
    assert r.status_code == 400, r.text
    assert "נמען" in r.json()["detail"]


def test_an_unknown_action_is_refused(client, admin_id):
    bid = _board(client, admin_id)
    r = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high", "actions": [{"key": "delete_board", "values": {}}]})
    assert r.status_code == 400, r.text


# ── who an extra action may name ────────────────────────────────────────────

def test_a_second_action_may_not_name_a_stranger_to_the_board(client, admin_id, guinea_id):
    """Refused when the rule is saved, like the recipe's own recipient: a rule
    that silently notifies nobody is found out by nobody."""
    bid = _board(client, admin_id)                      # guinea is NOT a member
    r = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "notify_person", "values": {"person": guinea_id}}]})
    assert r.status_code == 400, r.text
    assert "הוזמנו ללוח" in r.json()["detail"]


def test_a_second_action_naming_a_deactivated_account_is_refused(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    client.patch(f"/api/users/{guinea_id}", json={"actor_id": admin_id, "is_active": False})
    try:
        r = _add(client, bid, admin_id, "created_set_priority",
                 {"a_priority": "high",
                  "actions": [{"key": "notify_person", "values": {"person": guinea_id}}]})
        assert r.status_code == 400, r.text
        assert "מושבת" in r.json()["detail"]
    finally:
        client.patch(f"/api/users/{guinea_id}", json={"actor_id": admin_id, "is_active": True})


def test_a_recipient_removed_from_the_board_stops_the_whole_rule(client, admin_id, guinea_id):
    """Rule 5 reaches every action, and deliberately stops all of them.

    A permission the rule needs is gone, so the rule can no longer do what it
    says — and "it still does three of its four things" is exactly the quiet
    half-automation a board admin would never be told about. The rule is taken
    out of service and the person who owns it hears why, which is what already
    happened when the single action was the one with the missing recipient.
    """
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "notify_person", "values": {"person": guinea_id}}]}).json()
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    tid = _item(client, bid, admin_id)
    assert _task(tid)["priority"] != "high", "a rule missing a permission still ran"
    row = _get(client, bid, a["id"], admin_id)
    assert row["status"] == "paused_error", row["status"]
    runs = _runs(client, bid, admin_id)
    assert runs[0]["outcome"] == "skipped", runs[0]


# ── what the history says when only some of it happened ─────────────────────

def test_a_rule_whose_actions_all_do_nothing_is_a_skip(client, admin_id):
    """Unchanged behaviour for the whole rule: nothing happened, and the
    history says why rather than leaving a silent nothing."""
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "high",
              "actions": [{"key": "set_status", "values": {"status": "done"}}]}).json()
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "priority": "high"})
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "status": "done"})
    runs = [r for r in _runs(client, bid, admin_id) if r["automation_id"] == a["id"]]
    assert runs and runs[0]["outcome"] == "skipped", runs
    assert "כבר" in runs[0]["reason"], runs[0]["reason"]


def test_one_action_working_makes_the_rule_a_run(client, admin_id):
    """And the note names the dead end beside it, so "why did only some of it
    happen?" is answered in the same row."""
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "high",
              "actions": [{"key": "set_status", "values": {"status": "done"}}]}).json()
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "status": "done"})
    runs = [r for r in _runs(client, bid, admin_id) if r["automation_id"] == a["id"]]
    assert runs[0]["outcome"] == "ran", runs[0]
    assert "1 מתוך 2 פעולות בוצעו" in runs[0]["reason"], runs[0]["reason"]
    assert _task(tid)["priority"] == "high"


# ── a rule that fails halfway keeps what it had done ────────────────────────

def test_an_action_that_blows_up_stops_the_rest_and_keeps_what_worked(client, admin_id,
                                                                      guinea_id,
                                                                      monkeypatch):
    """The savepoint is the ACTION's, not the rule's — and it read the other
    way round until 12.2.

    The old reading was "a rule never half-happens": one savepoint around the
    whole list, so an action that raised took its predecessors with it. 12.2
    rules that out — "Retry מתחיל בפעולה הראשונה שנכשלה ואינו חוזר על פעולות
    שהצליחו" has nothing to resume from if the successes were undone.

    So: an ACTION never half-happens, a rule may, nothing after the failure
    runs, and the row says precisely which half went through. Which is the
    state somebody CAN reason about — the one they could not was a failure
    with no record of how far it got.
    """
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "assign_person", "values": {"person": guinea_id}},
                      {"key": "set_status", "values": {"status": "in_progress"}}]})

    real = cityos_main._apply_status_key

    def boom(db, task, key):
        raise RuntimeError("השרת נפל באמצע")

    monkeypatch.setattr(cityos_main, "_apply_status_key", boom)
    tid = _item(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "_apply_status_key", real)

    t = _task(tid)
    assert t["priority"] == "high", "the first action was undone"
    assert t["assignees"] != [], "the second action was undone"
    runs = _runs(client, bid, admin_id)
    assert runs and runs[0]["outcome"] == "failed", runs
    # and the third is recorded as the one that stopped it
    steps = (runs[0]["result"] or {}).get("steps") or []
    assert [x["status"] for x in steps] == ["succeeded", "succeeded",
                                            "failed_temporary"], steps


# ── what the screens are built from ─────────────────────────────────────────

def test_the_catalog_offers_the_actions_and_says_how_many(client, admin_id):
    d = client.get("/api/automations/recipes").json()
    assert d["max_actions"] == recipes.MAX_ACTIONS
    keys = {a["key"] for a in d["action_catalog"]}
    assert keys == set(recipes.ACTIONS), keys
    notify = next(a for a in d["action_catalog"] if a["key"] == "notify_person")
    # a recipient is its own kind of blank: five answers, four of them read off
    # the event rather than named in advance. "התראה" is the second — the
    # wording the notice carries, which may be left unset for the one this
    # system has always sent.
    assert notify["fields"] == [{"key": "person", "type": "recipient", "label": "נמען"},
                                {"key": "notice", "type": "notice", "label": "התראה"}]


def test_the_impact_screen_counts_what_every_action_writes(client, admin_id, guinea_id):
    """"What will this rule do to my board" may not be answered about the
    first of four."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "set_status", "values": {"status": "in_progress"}},
                          {"key": "assign_person", "values": {"person": guinea_id}}]}).json()
    d = client.get(f"/api/automations/{a['id']}/impact?user_id={admin_id}").json()
    assert len(d["writes"]) >= 3, d["writes"]
    assert any(r["name"] for r in d["recipients"]), d["recipients"]


def test_the_test_screen_lists_every_action_in_order(client, admin_id, guinea_id):
    """A dry run that described the first action would be answering about a
    different rule than the one being tested."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "set_status", "values": {"status": "in_progress"}},
                          {"key": "notify_person", "values": {"person": guinea_id}}]}).json()
    tid = _item(client, bid, admin_id, "פריט לבדיקה")
    d = client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}",
                    json={"task_id": tid}).json()
    whats = [x["what"] for x in d["actions"]]
    assert whats == ["שינוי עדיפות", "שינוי סטטוס", "שליחת התראה"], whats
    assert [x["order"] for x in d["actions"]] == [1, 2, 3], d["actions"]


def test_a_loop_is_seen_through_a_later_action_too(client, admin_id):
    """The loop warning asks what the rule produces. An action that is not the
    first produces events exactly as the first one does."""
    bid = _board(client, admin_id)
    first = _add(client, bid, admin_id, "created_set_priority",
                 {"a_priority": "high",
                  "actions": [{"key": "set_status", "values": {"status": "in_progress"}}]}).json()
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "in_progress", "a_priority": "low"})
    d = client.get(f"/api/automations/{first['id']}/impact?user_id={admin_id}").json()
    assert d["loop_risk"], "a rule listening for what the second action produces was not seen"


# ── the pure layer, where the rules about rules live ────────────────────────

def test_action_list_reads_both_halves_into_one_shape():
    """Everything downstream — the engine, the blockers, the impact, the test —
    asks this one question instead of each knowing where an action can hide."""
    cfg = {"a_priority": "high",
           "actions": [{"key": "notify_person", "values": {"person": 4}}]}
    got = recipes.action_list("created_set_priority", cfg)
    assert got == [{"key": "set_priority", "values": {"priority": "high"}, "index": 0},
                   {"key": "notify_person", "values": {"person": 4}, "index": 1}]


def test_an_action_from_a_version_we_no_longer_have_is_ignored_not_crashed():
    """A rule written by a newer build, read by an older one: the actions it
    still understands run, and the unknown one is not a 500."""
    cfg = {"a_priority": "high", "actions": [{"key": "launch_rocket", "values": {}}]}
    assert [x["key"] for x in recipes.action_list("created_set_priority", cfg)] \
        == ["set_priority"]


def test_every_recipe_action_declares_the_same_fields_as_the_catalog():
    """The recipe names its action's fields with an `a_` prefix and the catalog
    names them bare. They are the same fields, and action_list reads one shape
    out of both — so they may not drift."""
    for r in recipes.RECIPES:
        want = {f["key"][2:]: f["type"] for f in r["fields"] if f["key"].startswith("a_")}
        have = {f["key"]: f["type"] for f in recipes.action_fields(r["action"])}
        assert want == have, r["id"]


def test_a_change_to_the_extra_actions_reads_as_a_change_to_the_actions(client, admin_id,
                                                                        guinea_id):
    """Versions group a change into trigger / conditions / actions / permissions
    / order. The extra actions are actions — left ungrouped they landed under
    "פרטים" as a JSON list, which is the one form nobody can act on."""
    bid = _board(client, admin_id)
    _member(client, admin_id, bid, guinea_id)
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high",
              "actions": [{"key": "notify_person", "values": {"person": guinea_id}}]},
             status="draft").json()
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                     json={"config": {"a_priority": "high",
                                      "actions": [{"key": "set_status",
                                                   "values": {"status": "done"}}]}})
    assert r.status_code == 200, r.text
    d = client.get(f"/api/automations/{a['id']}/versions/compare?user_id={admin_id}").json()
    grp = next((g for g in d["groups"] if g["id"] == "actions"), None)
    assert grp, d["groups"]
    change = next(c for c in grp["changes"] if c["key"] == "actions")
    assert change["label"] == "פעולות נוספות"
    assert "שלח התראה" in change["from"] and "הסטטוס" in change["to"], change


def test_the_builder_offers_the_rest_of_the_then():
    """Driven harness: tests/frontend/automation_four_actions.mjs.

    Verified to fail: drop `actsReady` from the builder's readiness and one
    case goes red; let pickAct offer an action the rule already performs and
    two do; stop putting config.actions in the body and four do.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_four_actions.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
