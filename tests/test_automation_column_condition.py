"""תנאי על עמודה בלוח — "רק אם" over the board's own columns.

The conditions that existed asked about the handful of things every board has:
the status, the priority, the people on the item, its group, its due date. Most
of what a board actually MEANS lives in its own columns — a budget, a request
type, a contractor, a delivery date, a checkbox saying the file came in — and
none of it could be asked about at all. A rule that should fire "רק אם התקציב
הוא X" had to fire on everything and be undone by hand.

A column condition is three answers, because asking about a column takes three:
which column, what kind of column it is, and the value. So it stores
`{"col", "type", "value"}` where every other condition stores a scalar, and the
column's TYPE travels with it — a rule whose column was deleted has to stay
legible enough to fix, and "העמודה «תקציב» היא «1000»" says what a bare column
id does not.

Two things this group is really about:
  · the cell is read the way the board reads it — a multi-select cell holding
    two options answers "is" for either of them, a 0 is a value and not an
    empty cell, and "היום" is Israel's today and not the server's;
  · a condition that CANNOT be answered — the column was deleted, or changed
    type — never counts as true. A rule that quietly widened to everything its
    trigger catches is the worst outcome available here, so the rule holds its
    fire and the blockers say why.
"""
import pathlib
import shutil
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

import automations as recipes
import main as cityos_main
from models import Task

ROOT = pathlib.Path(__file__).resolve().parent.parent
IL = ZoneInfo("Asia/Jerusalem")


def _board(client, admin_id, name="לוח תנאי עמודה"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid, admin_id, cols):
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": cols})
    assert r.status_code == 200, r.text
    return r.json()["columns"]


def _col(client, bid, admin_id, **col):
    """One custom column on the board, returned as the server stored it."""
    return _cols(client, bid, admin_id, [col])[0]


def _add(client, bid, admin_id, conds, recipe_id="created_set_priority",
         config=None, **extra):
    cfg = dict(config or {"a_priority": "high"})
    cfg["conditions"] = conds
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": cfg, **extra})


def _item(client, bid, admin_id, fields=None, title="פריט"):
    """An item created WITH its cells, so the rule sees them when it fires."""
    body = {"board_id": bid, "title": title, "user_id": admin_id}
    if fields:
        body["custom_fields"] = fields
    return client.post("/api/tasks", json=body).json()["id"]


def _prio(tid):
    with Session(cityos_main.engine) as db:
        return cityos_main._task_priority_key(
            db.query(Task).filter(Task.id == tid).first())


def _fired(client, bid, admin_id, fields):
    """Did the rule run on an item with these cells? The action is
    "set priority to high", so the answer is on the item."""
    return _prio(_item(client, bid, admin_id, fields)) == "high"


def _cond(col, col_type, value, kind="column_is"):
    return [{"kind": kind, "value": {"col": col, "type": col_type, "value": value}}]


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]


# ── a number column ─────────────────────────────────────────────────────────

def test_a_rule_can_be_conditioned_on_a_number_column(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    r = _add(client, bid, admin_id, _cond(col["id"], "number", 1000))
    assert r.status_code == 200, r.text
    assert _fired(client, bid, admin_id, {col["id"]: 1000})
    assert not _fired(client, bid, admin_id, {col["id"]: 999})


def test_a_cell_holding_zero_is_a_value_and_not_an_empty_cell(client, admin_id):
    """The trap filter_ast is written around: 0 == False in Python, so a
    truthiness test files a budget of zero under "empty"."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    _add(client, bid, admin_id, _cond(col["id"], "number", 0))
    assert _fired(client, bid, admin_id, {col["id"]: 0})
    assert not _fired(client, bid, admin_id, {col["id"]: None})


def test_a_number_written_as_text_still_compares_as_a_number(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    _add(client, bid, admin_id, _cond(col["id"], "number", 1000))
    assert _fired(client, bid, admin_id, {col["id"]: "1000"})


# ── a status column, with the board's own vocabulary ────────────────────────

def test_a_rule_can_be_conditioned_on_a_status_column(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="status", title="שלב",
               options=[{"label": "הוגש", "color": "#00c875"},
                        {"label": "נדחה", "color": "#e2445c"}])
    opt = col["options"][0]
    _add(client, bid, admin_id, _cond(col["id"], "status", "הוגש"))
    assert _fired(client, bid, admin_id,
                  {col["id"]: {"id": opt["id"], "label": "הוגש", "color": opt["color"]}})
    assert not _fired(client, bid, admin_id, {col["id"]: {"label": "נדחה"}})


def test_the_negative_form_holds_for_everything_else(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="status", title="שלב",
               options=[{"label": "הוגש"}, {"label": "נדחה"}])
    _add(client, bid, admin_id, _cond(col["id"], "status", "נדחה", kind="column_is_not"))
    assert _fired(client, bid, admin_id, {col["id"]: {"label": "הוגש"}})
    assert not _fired(client, bid, admin_id, {col["id"]: {"label": "נדחה"}})


def test_an_empty_cell_is_not_the_value_and_is_not_its_opposite_either(client, admin_id):
    """"אינה «נדחה»" over an empty cell holds: an item with nothing chosen is
    not rejected. "היא «נדחה»" over the same cell does not."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="status", title="שלב",
               options=[{"label": "נדחה"}])
    _add(client, bid, admin_id, _cond(col["id"], "status", "נדחה"))
    assert not _fired(client, bid, admin_id, {})
    bid2 = _board(client, admin_id, "לוח תנאי עמודה 2")
    col2 = _col(client, bid2, admin_id, type="status", title="שלב",
                options=[{"label": "נדחה"}])
    _add(client, bid2, admin_id, _cond(col2["id"], "status", "נדחה", kind="column_is_not"))
    assert _fired(client, bid2, admin_id, {})


# ── a dropdown holds several options at once ────────────────────────────────

def test_is_on_a_multi_select_column_means_is_among_them(client, admin_id):
    """"רק אם סוג הפנייה הוא «תשתיות»" over a cell holding two types is true of
    that item — which is the reading of the words."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="dropdown", title="סוג פנייה",
               options=["תשתיות", "גינון", "חינוך"])
    _add(client, bid, admin_id, _cond(col["id"], "dropdown", "תשתיות"))
    assert _fired(client, bid, admin_id, {col["id"]: ["גינון", "תשתיות"]})
    assert not _fired(client, bid, admin_id, {col["id"]: ["גינון"]})


def test_two_values_on_one_multi_select_column_are_allowed(client, admin_id):
    """Both can hold at once, so they are not the contradiction that two values
    on a single-value column are."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="dropdown", title="סוג פנייה",
               options=["תשתיות", "גינון"])
    conds = _cond(col["id"], "dropdown", "תשתיות") + _cond(col["id"], "dropdown", "גינון")
    r = _add(client, bid, admin_id, conds)
    assert r.status_code == 200, r.text
    assert _fired(client, bid, admin_id, {col["id"]: ["תשתיות", "גינון"]})
    assert not _fired(client, bid, admin_id, {col["id"]: ["תשתיות"]})


def test_two_values_on_one_single_value_column_are_refused(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    conds = _cond(col["id"], "number", 10) + _cond(col["id"], "number", 20)
    r = _add(client, bid, admin_id, conds)
    assert r.status_code == 400, r.text
    assert "אותה עמודה" in r.json()["detail"]


def test_a_value_both_required_and_refused_is_refused(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    conds = (_cond(col["id"], "number", 10)
             + _cond(col["id"], "number", 10, kind="column_is_not"))
    r = _add(client, bid, admin_id, conds)
    assert r.status_code == 400, r.text


# ── a people column, and who may be named in one ────────────────────────────

def test_a_rule_can_be_conditioned_on_a_people_column(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    col = _col(client, bid, admin_id, type="people", title="מפקח")
    _add(client, bid, admin_id, _cond(col["id"], "people", guinea_id))
    assert _fired(client, bid, admin_id, {col["id"]: [guinea_id]})
    assert not _fired(client, bid, admin_id, {col["id"]: [admin_id]})


def test_a_people_column_cannot_name_a_stranger_to_the_board(client, admin_id, guinea_id):
    """The same bar a "רק אם X משויך" condition is held to: a rule conditioned
    on somebody who was never invited can never hold, so it is refused when it
    is written rather than discovered later."""
    bid = _board(client, admin_id)
    r = _add(client, bid, admin_id, _cond("ppl", "people", guinea_id))
    assert r.status_code == 400, r.text
    assert "להתנות" in r.json()["detail"]


# ── a date column, in Israel's day ──────────────────────────────────────────

def test_a_date_column_can_be_asked_about_a_fixed_day(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="date", title="תאריך אספקה")
    _add(client, bid, admin_id, _cond(col["id"], "date", "2026-10-19"))
    assert _fired(client, bid, admin_id, {col["id"]: "2026-10-19"})
    assert not _fired(client, bid, admin_id, {col["id"]: "2026-10-20"})


def test_today_is_israels_today(client, admin_id):
    """"היום" is not a fact about the server: an item dated for this evening in
    Jerusalem is already tomorrow's by UTC, and the rule has to agree with the
    board that shows it."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="date", title="תאריך אספקה")
    _add(client, bid, admin_id, _cond(col["id"], "date", "today"))
    today = datetime.now(IL).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(IL) + timedelta(days=1)).strftime("%Y-%m-%d")
    assert _fired(client, bid, admin_id, {col["id"]: today})
    assert not _fired(client, bid, admin_id, {col["id"]: tomorrow})


def test_a_dynamic_date_is_kept_as_the_token_it_was_chosen_as(client, admin_id):
    """Stored as "today", not as the day it was written on — a rule saved on
    Sunday still means "היום" on Thursday, and the sentence says so."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="date", title="תאריך אספקה")
    a = _add(client, bid, admin_id, _cond(col["id"], "date", "today")).json()
    assert a["conditions"][0]["value"]["value"] == "today"
    assert "היום" in a["condition_phrases"][0], a["condition_phrases"]


def test_a_date_that_is_neither_a_day_nor_a_token_is_refused(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="date", title="תאריך אספקה")
    r = _add(client, bid, admin_id, _cond(col["id"], "date", "בקרוב"))
    assert r.status_code == 400, r.text


# ── a checkbox ──────────────────────────────────────────────────────────────

def test_a_checkbox_column_can_be_asked_whether_it_is_ticked(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="checkbox", title="אושר")
    _add(client, bid, admin_id, _cond(col["id"], "checkbox", True))
    assert _fired(client, bid, admin_id, {col["id"]: True})
    assert not _fired(client, bid, admin_id, {col["id"]: False})
    assert not _fired(client, bid, admin_id, {})


def test_and_whether_it_is_not(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="checkbox", title="אושר")
    _add(client, bid, admin_id, _cond(col["id"], "checkbox", False))
    assert _fired(client, bid, admin_id, {})
    assert not _fired(client, bid, admin_id, {col["id"]: True})


# ── a column that cannot be asked about, and one that is gone ───────────────

def test_a_column_type_outside_the_matrix_is_refused(client, admin_id):
    """A type nobody has decided about is not available — which is what the
    field matrix is for. A connect column IS in it now (מקושר / אינו מקושר),
    so the one left out here is a type the engine does not know at all."""
    bid = _board(client, admin_id)
    r = _add(client, bid, admin_id, _cond("x", "a_type_nobody_defined", "7"))
    assert r.status_code == 400, r.text
    assert "סוג" in r.json()["detail"]


def test_an_empty_value_is_refused_even_in_a_draft(client, admin_id):
    """A condition with no value does not narrow the rule — it is the rule
    without the condition, which is the one thing a draft may not hide."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    r = _add(client, bid, admin_id, _cond(col["id"], "number", ""), status="draft")
    assert r.status_code == 400, r.text


def test_a_deleted_column_stops_the_rule_instead_of_widening_it(client, admin_id):
    """The whole point of the group. A condition that cannot be answered must
    never read as true: the rule would fire on everything its trigger catches,
    which is the opposite of what the condition was written for."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    a = _add(client, bid, admin_id, _cond(col["id"], "number", 1000)).json()
    assert _fired(client, bid, admin_id, {col["id"]: 1000})
    _cols(client, bid, admin_id, [])                      # the column is removed
    assert not _fired(client, bid, admin_id, {})
    runs = _runs(client, bid, admin_id)
    assert runs[0]["outcome"] == "skipped", runs[0]
    # and the history says which of the two silences this is: the rule did not
    # match, or the rule cannot be run at all
    assert "נמחקה" in runs[0]["reason"], runs[0]["reason"]
    assert a["id"] == runs[0]["automation_id"]


def test_an_unanswerable_condition_is_not_true_in_either_direction(client, admin_id):
    """The evaluator's own half of the line above, at its own level.

    _automation_blockers catches a deleted column before the rule is ever
    evaluated, which is where the skip in the case above comes from. This pins
    the layer under it: asked directly, a condition whose column cannot be
    found answers NO — and so does its negative form. An unanswerable question
    is not a question answered "no"; a `column_is_not` that read as true
    because nothing could be checked would widen the rule to everything its
    trigger catches, which is the one failure this whole group is written
    against. Two defences, because one of them is a list somebody may later
    narrow.
    """
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    spec = {"col": "col_that_never_existed", "type": "number", "value": 1}
    with Session(cityos_main.engine) as db:
        task = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._column_cond_holds(db, task, spec) is None
        assert cityos_main._condition_holds(db, task, "column_is", spec) is False
        assert cityos_main._condition_holds(db, task, "column_is_not", spec) is False


def test_a_column_that_changed_type_stops_it_too(client, admin_id):
    """The question the rule was written to ask no longer exists, and inventing
    a new one is not the engine's call."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    a = _add(client, bid, admin_id, _cond(col["id"], "number", 1000)).json()
    _cols(client, bid, admin_id, [{"id": col["id"], "type": "text", "title": "תקציב"}])
    tid = _item(client, bid, admin_id, {col["id"]: "1000"})
    assert _prio(tid) != "high"
    assert "סוג העמודה" in _runs(client, bid, admin_id)[0]["reason"]
    d = client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}",
                    json={"task_id": tid}).json()
    assert d["verdict"] == "blocked", d["summary"]
    assert any("סוג העמודה" in x for x in d["broken_dependencies"]), d


def test_the_sentence_still_names_a_deleted_column(client, admin_id):
    """What makes the rule fixable: the title it was written against, not an id
    nobody can look up any more."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    a = _add(client, bid, admin_id, _cond(col["id"], "number", 1000)).json()
    assert "«תקציב»" in a["sentence"], a["sentence"]


# ── how it reads, and what the screens show ─────────────────────────────────

def test_the_condition_reads_as_a_sentence(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    a = _add(client, bid, admin_id, _cond(col["id"], "number", 1000)).json()
    assert a["condition_phrases"] == ["העמודה תקציב היא 1000"], a["condition_phrases"]
    assert "ורק אם העמודה «תקציב» היא «1000»" in a["sentence"], a["sentence"]


def test_a_number_reads_as_a_number_and_not_as_a_float(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    a = _add(client, bid, admin_id, _cond(col["id"], "number", "1000")).json()
    assert a["conditions"][0]["value"]["value"] == 1000
    assert "«1000»" in a["sentence"], a["sentence"]


def test_the_test_screen_answers_the_condition_on_its_own(client, admin_id):
    """A test that reported only a verdict would leave the asker to guess which
    condition held it up — so the column's own cell is read back beside it."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    a = _add(client, bid, admin_id, _cond(col["id"], "number", 1000)).json()
    tid = _item(client, bid, admin_id, {col["id"]: 250})
    d = client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}",
                    json={"task_id": tid}).json()
    row = next(c for c in d["conditions"] if "תקציב" in c["label"])
    assert row["ok"] is False and row["expected"] == "1000" and row["actual"] == "250", row
    assert d["verdict"] == "would_skip", d["summary"]


def test_an_empty_cell_says_it_is_empty_rather_than_nothing(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    a = _add(client, bid, admin_id, _cond(col["id"], "number", 1000)).json()
    tid = _item(client, bid, admin_id)
    d = client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}",
                    json={"task_id": tid}).json()
    row = next(c for c in d["conditions"] if "תקציב" in c["label"])
    assert row["actual"] == "ריק", row


def test_the_history_names_the_condition_that_held_the_rule(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    _add(client, bid, admin_id, _cond(col["id"], "number", 1000))
    _item(client, bid, admin_id, {col["id"]: 7})
    runs = _runs(client, bid, admin_id)
    assert runs[0]["outcome"] == "skipped"
    assert "תקציב" in runs[0]["reason"], runs[0]["reason"]


def test_the_catalog_says_which_column_types_can_be_asked_about(client, admin_id):
    d = client.get("/api/automations/recipes").json()
    kinds = {c["kind"] for c in d["conditions"]}
    assert {"column_is", "column_is_not"} <= kinds
    assert d["column_kinds"]["number"] == ["number", "rating", "formula"], d["column_kinds"]
    assert "dropdown" in d["multi_column_types"]
    col = next(c for c in d["conditions"] if c["kind"] == "column_is")
    assert col["type"] == "column" and "…" in col["label"], col


# ── it is still one of three ─────────────────────────────────────────────────

def test_a_column_condition_counts_toward_the_three(client, admin_id):
    bid = _board(client, admin_id)
    cols = _cols(client, bid, admin_id, [{"type": "number", "title": f"ע{i}"} for i in range(4)])
    conds = []
    for c in cols:
        conds += _cond(c["id"], "number", 1)
    r = _add(client, bid, admin_id, conds)
    assert r.status_code == 400, r.text
    assert str(recipes.MAX_CONDITIONS) in r.json()["detail"]


def test_a_column_condition_sits_beside_the_others(client, admin_id):
    """Both halves of the if, in one rule: a built-in condition and a column
    one, ANDed like any two."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    conds = _cond(col["id"], "number", 1000) + [{"kind": "no_assignee"}]
    r = _add(client, bid, admin_id, conds)
    assert r.status_code == 200, r.text
    assert len(r.json()["condition_phrases"]) == 2


# ── the builder ─────────────────────────────────────────────────────────────

def test_the_builder_asks_for_a_type_then_a_column_then_a_value():
    """Driven harness: tests/frontend/automation_column_condition.mjs.

    Verified to fail: stop clearing the value when the column is changed and
    one case goes red; drop the column half from what save() sends and two do.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_column_condition.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
