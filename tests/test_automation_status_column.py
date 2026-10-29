"""אוטומציה על עמודת סטטוס — איזו עמודה, ולא רק איזה ערך.

A board has one built-in status and may carry any number of columns of type
status, each with a vocabulary of its own. Every `status` blank in a rule used
to mean the built-in one, so a board that tracks its work in a "שלב" column
could not fire a rule on it at all — only through "כאשר ערך העמודה משתנה",
which goes off on every change rather than on the one value somebody cares
about.

What is pinned here is that a rule says WHICH status it is about: the column
travels beside the value (`t_status` is answered by `t_status_col`), an empty
one is the board's own status — which is what every rule written before this
holds, and why nothing had to be migrated — and two columns that happen to
share an option label stay two different rules.
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from models import Task, Notification

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _board(client, admin_id, name="לוח עמודות סטטוס", invite=None):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    if invite is not None:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": invite, "role": "editor"})
    return bid


def _status_cols(client, bid, admin_id, *specs):
    """`specs` are (title, [labels]) pairs; answers with the stored columns."""
    cols = [{"type": "status", "title": t,
             "options": [{"label": x, "color": "#0073ea"} for x in labels]}
            for t, labels in specs]
    r = client.patch(f"/api/boards/{bid}", json={"columns": cols, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["columns"]


def _opt(col, label):
    return next(o["id"] for o in col["options"] if o["label"] == label)


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _add(client, bid, admin_id, recipe_id, config, active=True):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config, "is_active": active})


def _set_cell(client, tid, admin_id, col, label):
    """Write a status cell the way the grid writes one — the whole option, so
    it can be drawn without a lookup, with the id as the reference."""
    o = next(x for x in col["options"] if x["label"] == label)
    return client.patch(f"/api/tasks/{tid}?user_id={admin_id}",
                        json={"custom_fields": {col["id"]: {
                            "id": o["id"], "label": o["label"], "color": o["color"]}}})


def _notes_for(task_id, user_id):
    with Session(cityos_main.engine) as db:
        return [n for n in db.query(Notification)
                .filter(Notification.task_id == task_id).all() if n.user_id == user_id]


def _cell(tid, col_id):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        return (t.custom_fields or {}).get(col_id)


# ── the catalog says which blanks can name a column ────────────────────────

def test_the_catalog_offers_a_column_wording_for_a_status_blank(client, admin_id):
    """A rule about a named column is a different SENTENCE, not the same one
    with another blank filled — "כאשר «שלב» משתנה" has no "הסטטוס" left in it,
    so the builder has to be given both wordings rather than splice one."""
    d = client.get(f"/api/automations/recipes?user_id={admin_id}").json()
    one = next(r for r in d["recipes"] if r["id"] == "status_notify_person")
    assert one["status_fields"] == ["t_status"]
    assert "{t_status_col}" in one["sentence_parts"]["trigger_col"]
    assert "הסטטוס" not in one["sentence_parts"]["trigger_col"]
    # the built-in wording is untouched, which is what a board with no status
    # column of its own goes on seeing
    assert "כאשר הסטטוס משתנה" in one["sentence"]


def test_a_linked_items_status_cannot_name_a_column_of_this_board(client, admin_id):
    """"הסטטוס של פריט מקושר" lives on another board's item and is the built-in
    one by definition — offering this board's columns there would be offering a
    column the trigger cannot read."""
    d = client.get(f"/api/automations/recipes?user_id={admin_id}").json()
    one = next(r for r in d["recipes"] if r["id"] == "linked_status_set_status")
    assert one["status_fields"] == ["a_status"]        # the action, not the trigger


# ── the trigger ────────────────────────────────────────────────────────────

def test_a_rule_fires_when_its_own_status_column_reaches_the_value(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=guinea_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["הוגש", "אושר"]))
    r = _add(client, bid, admin_id, "status_notify_person",
             {"t_status": _opt(col, "אושר"), "t_status_col": col["id"],
              "a_person": guinea_id})
    assert r.status_code == 200, r.text
    tid = _item(client, bid, admin_id)

    # the wrong value in the right column does nothing
    _set_cell(client, tid, admin_id, col, "הוגש")
    assert not _notes_for(tid, guinea_id)

    _set_cell(client, tid, admin_id, col, "אושר")
    assert len(_notes_for(tid, guinea_id)) == 1


def test_the_boards_own_status_does_not_fire_a_columns_rule(client, admin_id, guinea_id):
    """The whole point of naming the column. A rule about "שלב" must not go off
    because the board's built-in status moved — they are different questions
    about the same item."""
    bid = _board(client, admin_id, invite=guinea_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["אושר"]))
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": _opt(col, "אושר"), "t_status_col": col["id"], "a_person": guinea_id})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    assert not _notes_for(tid, guinea_id)


def test_two_status_columns_sharing_a_label_stay_two_rules(client, admin_id, guinea_id):
    """Two columns may both offer «אושר», and they are not the same value: an
    option id belongs to the column that minted it."""
    bid = _board(client, admin_id, invite=guinea_id)
    plan, do = _status_cols(client, bid, admin_id,
                            ("שלב תכנון", ["אושר"]), ("שלב ביצוע", ["אושר"]))
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": _opt(plan, "אושר"), "t_status_col": plan["id"], "a_person": guinea_id})
    tid = _item(client, bid, admin_id)
    _set_cell(client, tid, admin_id, do, "אושר")
    assert not _notes_for(tid, guinea_id)
    _set_cell(client, tid, admin_id, plan, "אושר")
    assert len(_notes_for(tid, guinea_id)) == 1


def test_a_rule_on_the_boards_status_is_untouched_by_the_columns(client, admin_id, guinea_id):
    """The regression the whole design is shaped around: a rule written before
    a column could be named holds no column, and an empty one is the board's
    own status."""
    bid = _board(client, admin_id, invite=guinea_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["done"]))
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": "done", "a_person": guinea_id})
    tid = _item(client, bid, admin_id)
    # a column option that happens to be spelled like a board status is still
    # not one, so this must do nothing
    _set_cell(client, tid, admin_id, col, "done")
    assert not _notes_for(tid, guinea_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    assert len(_notes_for(tid, guinea_id)) == 1


# ── the action ─────────────────────────────────────────────────────────────

def test_an_action_writes_the_status_column_it_names(client, admin_id):
    bid = _board(client, admin_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["טרם החל", "בעבודה"]))
    r = _add(client, bid, admin_id, "created_set_status",
             {"a_status": _opt(col, "בעבודה"), "a_status_col": col["id"]})
    assert r.status_code == 200, r.text
    tid = _item(client, bid, admin_id, "פריט חדש")
    # the cell carries the whole option, the way the grid draws it
    assert _cell(tid, col["id"]) == {"id": _opt(col, "בעבודה"), "label": "בעבודה",
                                     "color": "#0073ea"}
    # and the board's own status was not touched
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._st_of(t) != "done"


def test_writing_one_status_column_can_set_off_a_rule_on_it(client, admin_id, guinea_id):
    """A status column written by a rule reports the value it reached, not
    merely that it moved — otherwise a chain could only ever be built on
    "ערך העמודה משתנה"."""
    bid = _board(client, admin_id, invite=guinea_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["בעבודה"]))
    _add(client, bid, admin_id, "created_set_status",
         {"a_status": _opt(col, "בעבודה"), "a_status_col": col["id"]})
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": _opt(col, "בעבודה"), "t_status_col": col["id"], "a_person": guinea_id})
    tid = _item(client, bid, admin_id)
    assert len(_notes_for(tid, guinea_id)) == 1


def test_two_set_status_actions_are_allowed_on_two_different_columns(client, admin_id):
    """«שנה את הסטטוס» twice is one write twice over — unless they are about
    different status columns, where the second overwrites nothing."""
    bid = _board(client, admin_id)
    plan, do = _status_cols(client, bid, admin_id,
                            ("שלב תכנון", ["אושר"]), ("שלב ביצוע", ["התחיל"]))
    ok = _add(client, bid, admin_id, "created_set_status",
              {"a_status": _opt(plan, "אושר"), "a_status_col": plan["id"],
               "actions": [{"key": "set_status",
                            "values": {"status": _opt(do, "התחיל"),
                                       "status_col": do["id"]}}]})
    assert ok.status_code == 200, ok.text
    tid = _item(client, bid, admin_id)
    assert (_cell(tid, plan["id"]) or {}).get("label") == "אושר"
    assert (_cell(tid, do["id"]) or {}).get("label") == "התחיל"

    # the same column twice is still refused — that one really does overwrite
    clash = _add(client, bid, admin_id, "created_set_status",
                 {"a_status": _opt(plan, "אושר"), "a_status_col": plan["id"],
                  "actions": [{"key": "set_status",
                               "values": {"status": _opt(plan, "אושר"),
                                          "status_col": plan["id"]}}]})
    assert clash.status_code == 400, clash.text


# ── how it reads, and what breaks it ───────────────────────────────────────

def test_the_sentence_names_the_column_it_is_about(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=guinea_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["אושר"]))
    made = _add(client, bid, admin_id, "status_notify_person",
                {"t_status": _opt(col, "אושר"), "t_status_col": col["id"],
                 "a_person": guinea_id}).json()
    assert "«שלב»" in made["sentence"] and "«אושר»" in made["sentence"]
    assert "הסטטוס" not in made["sentence"]


def test_renaming_the_column_carries_the_sentence_with_it(client, admin_id, guinea_id):
    """The rule stores the id and the sentence reads the title off the board
    every time — the same promise "ערך העמודה משתנה" already makes."""
    bid = _board(client, admin_id, invite=guinea_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["אושר"]))
    aid = _add(client, bid, admin_id, "status_notify_person",
               {"t_status": _opt(col, "אושר"), "t_status_col": col["id"],
                "a_person": guinea_id}).json()["id"]
    client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [
        dict(col, title="שלב הפרויקט")]})
    rows = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()["automations"]
    one = next(r for r in rows if r["id"] == aid)
    assert "«שלב הפרויקט»" in one["sentence"]


def test_a_rule_whose_status_column_is_gone_says_so(client, admin_id, guinea_id):
    """A rule waiting on a deleted column never fires again, and does it
    silently — it still looks active. That is what a blocker is for."""
    bid = _board(client, admin_id, invite=guinea_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["אושר"]))
    aid = _add(client, bid, admin_id, "status_notify_person",
               {"t_status": _opt(col, "אושר"), "t_status_col": col["id"],
                "a_person": guinea_id}).json()["id"]
    client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": []})
    d = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"automation_id": aid}).json()
    assert any("עמודת הסטטוס" in t for t in d["blockers"]), d


def test_deleting_a_status_column_warns_about_the_rules_on_it(client, admin_id, guinea_id):
    """"דורשות טיפול" is the preview that makes a deletion safe to agree to; a
    dependency it misses is a deletion somebody was told was safe."""
    bid = _board(client, admin_id, invite=guinea_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["אושר"]))
    aid = _add(client, bid, admin_id, "status_notify_person",
               {"t_status": _opt(col, "אושר"), "t_status_col": col["id"],
                "a_person": guinea_id}).json()["id"]
    d = client.get(f"/api/boards/{bid}/automations/dependents"
                   f"?kind=column&ref={col['id']}&user_id={admin_id}").json()
    assert aid in {x["id"] for x in d["dependents"]}, d


# ── the builder ────────────────────────────────────────────────────────────

def test_the_builder_asks_which_status_before_which_value():
    """Driven harness: tests/frontend/automation_status_column.mjs.

    Verified to fail: drop the column half from what save() sends and one case
    goes red; stop clearing the value when the column changes and another does.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_status_column.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


# ── what a rule is reported as writing ─────────────────────────────────────

def test_a_rule_on_a_status_column_does_not_fight_over_the_boards_status(
        client, admin_id):
    """"כלל אחר כותב לאותו שדה" is a warning somebody acts on, so a false one
    costs more than none. A rule setting the "שלב" column writes that column's
    cell — it is not in competition with every rule that sets the board's own
    status, and the warning is keyed by the action alone unless something tells
    it otherwise."""
    bid = _board(client, admin_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["אושר"]))
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    d = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "created_set_status",
                          "config": {"a_status": _opt(col, "אושר"),
                                     "a_status_col": col["id"]}}).json()
    assert not [w for w in d["warnings"] if "כותבת גם היא" in w["text"]], d["warnings"]


def test_but_two_rules_on_the_same_board_status_still_warn(client, admin_id):
    """The other half of the line above — the warning still does its job."""
    bid = _board(client, admin_id)
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    d = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "created_set_status",
                          "config": {"a_status": "in_progress"}}).json()
    assert [w for w in d["warnings"]
            if "כותבת גם היא" in w["text"] and "סטטוס" in w["text"]], d["warnings"]


# ── one status moving another ──────────────────────────────────────────────

def test_a_status_change_is_offered_the_set_status_action(client, admin_id):
    """Every other trigger has paired with "שנה את הסטטוס" from the start.
    This one had not: with one status per board the pair could only talk to
    itself, so it was left out — and with status columns it is the commonest
    thing two of them are for."""
    d = client.get(f"/api/automations/recipes?user_id={admin_id}").json()
    assert "status_set_status" in {r["id"] for r in d["recipes"]}
    # and "אוטומציה מאפס" walks the same catalog, so it offers it too
    one = next(b for b in d["blueprint"] if b["trigger"] == "status_changes_to")
    assert "set_status" in {x["action"] for x in one["actions"]}, one["actions"]


def test_one_status_column_can_move_another(client, admin_id):
    bid = _board(client, admin_id)
    plan, do = _status_cols(client, bid, admin_id,
                            ("שלב תכנון", ["הוגש", "אושר"]), ("שלב ביצוע", ["טרם", "התחיל"]))
    r = _add(client, bid, admin_id, "status_set_status",
             {"t_status": _opt(plan, "אושר"), "t_status_col": plan["id"],
              "a_status": _opt(do, "התחיל"), "a_status_col": do["id"]})
    assert r.status_code == 200, r.text
    tid = _item(client, bid, admin_id)
    _set_cell(client, tid, admin_id, plan, "הוגש")
    assert _cell(tid, do["id"]) is None            # the wrong value moves nothing
    _set_cell(client, tid, admin_id, plan, "אושר")
    assert (_cell(tid, do["id"]) or {}).get("label") == "התחיל"


def test_the_boards_own_status_can_move_a_column(client, admin_id):
    bid = _board(client, admin_id)
    col, = _status_cols(client, bid, admin_id, ("שלב ביצוע", ["הסתיים"]))
    _add(client, bid, admin_id, "status_set_status",
         {"t_status": "done", "a_status": _opt(col, "הסתיים"), "a_status_col": col["id"]})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    assert (_cell(tid, col["id"]) or {}).get("label") == "הסתיים"


def test_and_a_column_can_move_the_boards_own_status(client, admin_id):
    bid = _board(client, admin_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["אושר"]))
    _add(client, bid, admin_id, "status_set_status",
         {"t_status": _opt(col, "אושר"), "t_status_col": col["id"], "a_status": "done"})
    tid = _item(client, bid, admin_id)
    _set_cell(client, tid, admin_id, col, "אושר")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._st_of(t) == "done"


def test_a_rule_pointed_at_its_own_status_fires_once_and_stops(client, admin_id):
    """The reading the pair was once left out for. It is harmless: the value
    the rule writes is not the value it waits for, so the change it makes
    cannot set it off again."""
    bid = _board(client, admin_id)
    col, = _status_cols(client, bid, admin_id, ("שלב", ["אושר", "הסתיים"]))
    _add(client, bid, admin_id, "status_set_status",
         {"t_status": _opt(col, "אושר"), "t_status_col": col["id"],
          "a_status": _opt(col, "הסתיים"), "a_status_col": col["id"]})
    tid = _item(client, bid, admin_id)
    _set_cell(client, tid, admin_id, col, "אושר")
    assert (_cell(tid, col["id"]) or {}).get("label") == "הסתיים"
    runs = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]
    assert len([r for r in runs if r["outcome"] == "ran"]) == 1, runs


def test_it_reads_as_one_sentence_about_two_columns(client, admin_id):
    bid = _board(client, admin_id)
    plan, do = _status_cols(client, bid, admin_id,
                            ("שלב תכנון", ["אושר"]), ("שלב ביצוע", ["התחיל"]))
    made = _add(client, bid, admin_id, "status_set_status",
                {"t_status": _opt(plan, "אושר"), "t_status_col": plan["id"],
                 "a_status": _opt(do, "התחיל"), "a_status_col": do["id"]}).json()
    assert made["sentence"] == ("כאשר «שלב תכנון» משתנה ל«אושר», "
                                "שנה את «שלב ביצוע» ל«התחיל»"), made["sentence"]


# ── the loop check knows which column ──────────────────────────────────────

def _cycles(client, bid, admin_id, config):
    d = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "status_set_status", "config": config}).json()
    return [w for w in d["warnings"] if w.get("cycle")]


def test_moving_another_column_is_not_a_loop_risk(client, admin_id):
    """"סיכון ללולאה" on the impact screen is a guess from the shape of two
    rules, and a guess that fires on the commonest correct use of the feature
    is a line people stop reading. A rule watching "שלב תכנון" is not set off
    by one that writes "שלב ביצוע" — they are two different columns, and the
    check has to know that or it names every status rule on the board."""
    bid = _board(client, admin_id)
    plan, do = _status_cols(client, bid, admin_id,
                            ("שלב תכנון", ["אושר"]), ("שלב ביצוע", ["התחיל"]))
    # another rule watching the SAME column this one is triggered by, which is
    # not the column it writes
    other = _add(client, bid, admin_id, "status_notify_assignees",
                 {"t_status": _opt(plan, "אושר"), "t_status_col": plan["id"]}).json()["id"]
    aid = _add(client, bid, admin_id, "status_set_status",
               {"t_status": _opt(plan, "אושר"), "t_status_col": plan["id"],
                "a_status": _opt(do, "התחיל"), "a_status_col": do["id"]}).json()["id"]
    d = client.get(f"/api/automations/{aid}/impact?user_id={admin_id}").json()
    assert other not in {x["id"] for x in d["loop_risk"]}, d["loop_risk"]


def test_but_a_rule_watching_the_column_it_writes_is_named(client, admin_id):
    """The other half — the check still does its job within one column."""
    bid = _board(client, admin_id)
    plan, do = _status_cols(client, bid, admin_id,
                            ("שלב תכנון", ["אושר"]), ("שלב ביצוע", ["התחיל"]))
    other = _add(client, bid, admin_id, "status_notify_assignees",
                 {"t_status": _opt(do, "התחיל"), "t_status_col": do["id"]}).json()["id"]
    aid = _add(client, bid, admin_id, "status_set_status",
               {"t_status": _opt(plan, "אושר"), "t_status_col": plan["id"],
                "a_status": _opt(do, "התחיל"), "a_status_col": do["id"]}).json()["id"]
    d = client.get(f"/api/automations/{aid}/impact?user_id={admin_id}").json()
    assert other in {x["id"] for x in d["loop_risk"]}, d["loop_risk"]


def test_but_two_columns_feeding_each_other_is(client, admin_id):
    """The other half: «תכנון» moves «ביצוע» and «ביצוע» moves «תכנון» is a
    real ring, however sensible each half looks on its own."""
    bid = _board(client, admin_id)
    plan, do = _status_cols(client, bid, admin_id,
                            ("שלב תכנון", ["אושר"]), ("שלב ביצוע", ["התחיל"]))
    _add(client, bid, admin_id, "status_set_status",
         {"t_status": _opt(do, "התחיל"), "t_status_col": do["id"],
          "a_status": _opt(plan, "אושר"), "a_status_col": plan["id"]})
    assert _cycles(client, bid, admin_id,
                   {"t_status": _opt(plan, "אושר"), "t_status_col": plan["id"],
                    "a_status": _opt(do, "התחיל"), "a_status_col": do["id"]}), \
        "a ring between two status columns was not reported"


def test_a_mixed_rule_names_a_column_on_one_side_only(client, admin_id):
    """status_set_status is the first recipe whose trigger AND action can each
    name a column, so it is the first that has four readings rather than two.
    Naming one on the action side must leave the trigger half alone."""
    bid = _board(client, admin_id)
    col, = _status_cols(client, bid, admin_id, ("שלב ביצוע", ["התחיל"]))
    made = _add(client, bid, admin_id, "status_set_status",
                {"t_status": "done", "a_status": _opt(col, "התחיל"),
                 "a_status_col": col["id"]}).json()
    assert made["sentence"] == ("כאשר הסטטוס משתנה ל«בוצע», "
                                "שנה את «שלב ביצוע» ל«התחיל»"), made["sentence"]


def test_each_half_of_a_sentence_is_served_in_both_readings(client, admin_id):
    """The builder composes while somebody is still choosing, so it is given
    both readings of each half rather than whole sentences — four strings per
    recipe would be a table that grows with every recipe added.

    Pinned by reassembly over the whole catalog: a half that drifted from what
    sentence() produces would show one wording while the rule was being written
    and another everywhere it is read afterwards.
    """
    d = client.get(f"/api/automations/recipes?user_id={admin_id}").json()
    for r in d["recipes"]:
        p = r["sentence_parts"]
        assert p["trigger"] + ", " + p["action"] == r["sentence"], r["id"]
    one = next(r for r in d["recipes"] if r["id"] == "status_set_status")
    assert one["sentence_parts"]["trigger_col"] and one["sentence_parts"]["action_col"]
    # a linked item's status is the built-in one by definition, so that half
    # offers no column reading at all
    linked = next(r for r in d["recipes"] if r["id"] == "linked_status_set_status")
    assert linked["sentence_parts"]["trigger_col"] == ""
    assert linked["sentence_parts"]["action_col"]


# ── finding it ─────────────────────────────────────────────────────────────

def test_the_template_is_listed_by_name_and_not_as_a_bare_sentence(client, admin_id):
    """How the capability went missing after it was built.

    The library renders a template's NAME when it has one and its bare sentence
    when it does not. This one had none, so it sat 52nd of 59 under
    "כאשר הסטטוס משתנה ל…, שנה את הסטטוס ל…" — the one reading of it that looks
    like a rule talking to itself, with nothing to say that the status it
    writes may be a different column from the one it watches.
    """
    bid = _board(client, admin_id)
    _status_cols(client, bid, admin_id, ("שלב", ["אושר"]))
    d = client.get(f"/api/boards/{bid}/automations/templates?user_id={admin_id}").json()
    one = next(t for t in d["templates"] if t["id"] == "status_set_status")
    assert "עמודת סטטוס" in one["title"], one["title"]
    assert one["recommended"] is True
    # recommended templates are listed first, so it is on the first screen
    assert d["templates"].index(one) < len(
        [t for t in d["templates"] if t["recommended"]])
    # and the two halves of the answer agree about which those are
    assert one["id"] in d["recommended"]


def test_it_is_found_by_searching_for_the_thing_it_does(client, admin_id):
    """The search reads the title, so naming it is also what makes it
    findable — "עמודה" appears nowhere in its sentence or its trigger."""
    bid = _board(client, admin_id)
    d = client.get(f"/api/boards/{bid}/automations/templates"
                   f"?q=עמודת סטטוס&user_id={admin_id}").json()
    assert [t["id"] for t in d["templates"]] == ["status_set_status"], \
        [t["id"] for t in d["templates"]]
