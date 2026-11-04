"""תנאי שמשווה עמודה לעמודה — the other side of a column condition is a column.

A column condition has always compared one of the board's columns with a value
somebody typed when the rule was written. That cannot ask the question people
actually arrive with once a board holds two columns that mean something to each
other: "רק אם «תאריך סיום» אחרי «תאריך התחלה»", "רק אם «בפועל» גדול
מ«מתוכנן»". The answer is not a date or a number — it is whatever the OTHER
column happens to say on that item, which is only known when the rule runs.

So a side of a column condition is now either a literal, as it always was, or
a reference to a second column read off the SAME item at the moment the rule
fires: ``{"col": "<id>", "type": "<the column's own type>"}``.

What this group pins, and why each one matters:

  · both ends must be the same KIND, and a column may not be compared with
    itself. Either one is a rule that can never hold or always holds, and this
    engine refuses those where they are WRITTEN rather than skipping them for
    ever afterwards;
  · a right-hand cell nobody filled in makes the condition unanswerable, and
    the rule holds its fire. This is the one that must never regress:
    filter_ast reads a missing value as "nothing chosen yet, match everything",
    so letting an empty cell through would quietly widen the rule to every
    item its trigger catches — the worst outcome available here;
  · the compared column is a DEPENDENCY. Deleting it is warned about before
    the fact and reported after it, exactly as deleting the column being asked
    about is — it is the easier of the two to delete without anyone connecting
    it to the rule that silently stopped firing;
  · the rule still reads as a sentence. "הערך שבעמודה «תאריך התחלה»" and not a
    bare name, which in that slot would read as the literal text being looked
    for.
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

import main as cityos_main
from models import Task


def _board(client, admin_id, name="לוח השוואת עמודות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid, admin_id, cols):
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": cols})
    assert r.status_code == 200, r.text
    return r.json()["columns"]


def _col(client, bid, admin_id, **col):
    """One more custom column on the board, as the server stored it.

    The PATCH replaces the whole list, so what is already there is sent back
    with it — a board here carries two columns on purpose, and adding the
    second must not take the first away.
    """
    have = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
    keep = [c for c in have if not str(c.get("id", "")).startswith("sys_")]
    out = _cols(client, bid, admin_id, keep + [col])
    return out[-1]


def _ref(col_id, col_type):
    """The other side, naming a column instead of holding a value."""
    return {"col": col_id, "type": col_type}


def _add(client, bid, admin_id, value, col, col_type, op=None,
         kind="column_is", value2=None):
    spec = {"col": col, "type": col_type, "value": value}
    if op:
        spec["op"] = op
    if value2 is not None:
        spec["value2"] = value2
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": "created_set_priority",
                             "config": {"a_priority": "high",
                                        "conditions": [{"kind": kind, "value": spec}]}})


def _prio(tid):
    with Session(cityos_main.engine) as db:
        return cityos_main._task_priority_key(
            db.query(Task).filter(Task.id == tid).first())


def _fired(client, bid, admin_id, fields):
    """Did the rule run on an item with these cells? The action is "set the
    priority to high", so the answer is on the item itself."""
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id,
                                          "custom_fields": fields}).json()["id"]
    return _prio(tid) == "high"


def _two_dates(client, bid, admin_id):
    start = _col(client, bid, admin_id, type="date", title="תאריך התחלה")
    end = _col(client, bid, admin_id, type="date", title="תאריך סיום")
    return start, end


# ── the comparison itself ───────────────────────────────────────────────────

def test_one_date_column_is_compared_with_another(client, admin_id):
    bid = _board(client, admin_id)
    start, end = _two_dates(client, bid, admin_id)
    r = _add(client, bid, admin_id, _ref(start["id"], "date"),
             end["id"], "date", op="after")
    assert r.status_code == 200, r.text
    day = date.today()
    assert _fired(client, bid, admin_id,
                  {start["id"]: day.isoformat(),
                   end["id"]: (day + timedelta(days=3)).isoformat()})
    assert not _fired(client, bid, admin_id,
                      {start["id"]: day.isoformat(),
                       end["id"]: (day - timedelta(days=3)).isoformat()})


def test_one_number_column_is_compared_with_another(client, admin_id):
    bid = _board(client, admin_id)
    planned = _col(client, bid, admin_id, type="number", title="מתוכנן")
    actual = _col(client, bid, admin_id, type="number", title="בפועל")
    assert _add(client, bid, admin_id, _ref(planned["id"], "number"),
                actual["id"], "number", op="gt").status_code == 200
    assert _fired(client, bid, admin_id, {planned["id"]: 1000, actual["id"]: 1200})
    assert not _fired(client, bid, admin_id, {planned["id"]: 1000, actual["id"]: 900})


def test_a_zero_on_the_other_side_is_a_value_and_not_an_empty_cell(client, admin_id):
    """The same trap filter_ast is written around, now on the side this change
    added: 0 == False in Python, and a truthiness test on the compared cell
    would file a budget of zero under "there is nothing to compare with"."""
    bid = _board(client, admin_id)
    planned = _col(client, bid, admin_id, type="number", title="מתוכנן")
    actual = _col(client, bid, admin_id, type="number", title="בפועל")
    _add(client, bid, admin_id, _ref(planned["id"], "number"),
         actual["id"], "number", op="gt")
    assert _fired(client, bid, admin_id, {planned["id"]: 0, actual["id"]: 5})


def test_two_text_columns_are_compared_as_text(client, admin_id):
    bid = _board(client, admin_id)
    asked = _col(client, bid, admin_id, type="text", title="מבקש")
    owner = _col(client, bid, admin_id, type="text", title="מטפל")
    _add(client, bid, admin_id, _ref(asked["id"], "text"), owner["id"], "text")
    assert _fired(client, bid, admin_id, {asked["id"]: "דנה", owner["id"]: "דנה"})
    assert not _fired(client, bid, admin_id, {asked["id"]: "דנה", owner["id"]: "יואב"})


def test_a_range_may_name_a_column_on_each_end(client, admin_id):
    """"בין תאריך ההתחלה לתאריך הסיום" — the case two literals cannot express
    at all, since neither end of the range is known when the rule is written."""
    bid = _board(client, admin_id)
    start, end = _two_dates(client, bid, admin_id)
    mid = _col(client, bid, admin_id, type="date", title="אבן דרך")
    day = date.today()
    r = _add(client, bid, admin_id, _ref(start["id"], "date"), mid["id"], "date",
             op="between", value2=_ref(end["id"], "date"))
    assert r.status_code == 200, r.text
    assert _fired(client, bid, admin_id,
                  {start["id"]: day.isoformat(),
                   end["id"]: (day + timedelta(days=10)).isoformat(),
                   mid["id"]: (day + timedelta(days=4)).isoformat()})
    assert not _fired(client, bid, admin_id,
                      {start["id"]: day.isoformat(),
                       end["id"]: (day + timedelta(days=10)).isoformat(),
                       mid["id"]: (day + timedelta(days=40)).isoformat()})


def test_the_negative_form_asks_the_same_question_backwards(client, admin_id):
    bid = _board(client, admin_id)
    asked = _col(client, bid, admin_id, type="text", title="מבקש")
    owner = _col(client, bid, admin_id, type="text", title="מטפל")
    _add(client, bid, admin_id, _ref(asked["id"], "text"), owner["id"], "text",
         kind="column_is_not")
    assert _fired(client, bid, admin_id, {asked["id"]: "דנה", owner["id"]: "יואב"})
    assert not _fired(client, bid, admin_id, {asked["id"]: "דנה", owner["id"]: "דנה"})


# ── a comparison that cannot be made ────────────────────────────────────────

def test_an_empty_compared_cell_holds_the_rule_s_fire(client, admin_id):
    """The one that must never regress. A missing value reaches filter_ast as
    "nothing chosen yet", which matches EVERYTHING — so an empty cell on the
    other side has to stop the condition before it gets there."""
    bid = _board(client, admin_id)
    planned = _col(client, bid, admin_id, type="number", title="מתוכנן")
    actual = _col(client, bid, admin_id, type="number", title="בפועל")
    _add(client, bid, admin_id, _ref(planned["id"], "number"),
         actual["id"], "number", op="gt")
    assert not _fired(client, bid, admin_id, {actual["id"]: 1200})


def test_an_empty_compared_cell_does_not_make_the_NEGATIVE_form_true_either(
        client, admin_id):
    """"אינה" over an unanswerable condition is not "yes". Both forms hold
    their fire, which is what _condition_holds does with a None."""
    bid = _board(client, admin_id)
    asked = _col(client, bid, admin_id, type="text", title="מבקש")
    owner = _col(client, bid, admin_id, type="text", title="מטפל")
    _add(client, bid, admin_id, _ref(asked["id"], "text"), owner["id"], "text",
         kind="column_is_not")
    assert not _fired(client, bid, admin_id, {owner["id"]: "יואב"})


def test_a_people_column_compares_only_while_it_names_one_person(client, admin_id):
    """Two names in the compared column is not two questions. Picking the first
    of them would be the engine deciding which colleague the rule meant."""
    bid = _board(client, admin_id)
    one = _col(client, bid, admin_id, type="people", title="אחראי")
    two = _col(client, bid, admin_id, type="people", title="מנהל פרויקט")
    assert _add(client, bid, admin_id, _ref(two["id"], "people"),
                one["id"], "people", op="has").status_code == 200
    assert _fired(client, bid, admin_id,
                  {one["id"]: [admin_id], two["id"]: [admin_id]})
    assert not _fired(client, bid, admin_id,
                      {one["id"]: [admin_id], two["id"]: []})


def test_a_compared_column_that_was_deleted_holds_the_rule_s_fire(client, admin_id):
    bid = _board(client, admin_id)
    planned = _col(client, bid, admin_id, type="number", title="מתוכנן")
    actual = _col(client, bid, admin_id, type="number", title="בפועל")
    _add(client, bid, admin_id, _ref(planned["id"], "number"),
         actual["id"], "number", op="gt")
    _cols(client, bid, admin_id, [{"id": actual["id"], "type": "number",
                                   "title": "בפועל"}])
    assert not _fired(client, bid, admin_id, {actual["id"]: 1200})


def test_a_rule_whose_compared_column_is_gone_cannot_be_switched_back_on(
        client, admin_id):
    """A rule that looks active and does nothing is the silent failure this
    system refuses to ship. The engine's own re-check is what the switch asks,
    so the refusal says which column went missing rather than "not allowed"."""
    bid = _board(client, admin_id)
    planned = _col(client, bid, admin_id, type="number", title="מתוכנן")
    actual = _col(client, bid, admin_id, type="number", title="בפועל")
    aid = _add(client, bid, admin_id, _ref(planned["id"], "number"),
               actual["id"], "number", op="gt").json()["id"]
    _cols(client, bid, admin_id, [{"id": actual["id"], "type": "number",
                                   "title": "בפועל"}])
    client.patch(f"/api/automations/{aid}?user_id={admin_id}",
                 json={"status": "paused"})
    r = client.patch(f"/api/automations/{aid}?user_id={admin_id}",
                     json={"status": "active"})
    assert r.status_code == 400, r.text
    assert "משווה" in r.json()["detail"], r.text


def test_deleting_the_compared_column_warns_about_the_rule_first(client, admin_id):
    """"לפני מחיקת שדה המערכת תציג את האוטומציות התלויות" — and the column on
    the far side of a comparison is a dependency like any other."""
    bid = _board(client, admin_id)
    planned = _col(client, bid, admin_id, type="number", title="מתוכנן")
    actual = _col(client, bid, admin_id, type="number", title="בפועל")
    aid = _add(client, bid, admin_id, _ref(planned["id"], "number"),
               actual["id"], "number", op="gt").json()["id"]
    d = client.get(f"/api/boards/{bid}/automations/dependents"
                   f"?kind=column&ref={planned['id']}&user_id={admin_id}").json()
    hit = next((x for x in d["dependents"] if x["id"] == aid), None)
    assert hit and "תנאי" in hit["uses"], d


# ── what may not be written at all ──────────────────────────────────────────

def test_a_column_may_not_be_compared_with_itself(client, admin_id):
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="number", title="תקציב")
    r = _add(client, bid, admin_id, _ref(col["id"], "number"), col["id"], "number")
    assert r.status_code == 400, r.text
    assert "לעצמה" in r.json()["detail"], r.text


def test_the_two_ends_must_be_the_same_kind(client, admin_id):
    bid = _board(client, admin_id)
    num = _col(client, bid, admin_id, type="number", title="תקציב")
    day = _col(client, bid, admin_id, type="date", title="מועד")
    r = _add(client, bid, admin_id, _ref(day["id"], "date"), num["id"], "number")
    assert r.status_code == 400, r.text
    assert "אותו סוג" in r.json()["detail"], r.text


def test_a_checkbox_has_no_side_to_put_a_column_in(client, admin_id):
    """Its questions — מסומן, אינו מסומן — take no value at all, so there is
    nowhere for a second column to go."""
    bid = _board(client, admin_id)
    box = _col(client, bid, admin_id, type="checkbox", title="אושר")
    other = _col(client, bid, admin_id, type="checkbox", title="שולם")
    r = _add(client, bid, admin_id, _ref(other["id"], "checkbox"),
             box["id"], "checkbox", op="yes")
    # the operator takes no value, so the reference is simply not stored
    assert r.status_code == 200, r.text
    cfg = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
    stored = cfg["automations"][0]["conditions"][0]["value"]
    assert "value" not in stored or stored.get("value") is None, stored


# ── and it still reads as a sentence ────────────────────────────────────────

def test_the_rule_reads_as_a_sentence_naming_the_other_column(client, admin_id):
    bid = _board(client, admin_id)
    start, end = _two_dates(client, bid, admin_id)
    _add(client, bid, admin_id, _ref(start["id"], "date"), end["id"], "date",
         op="after")
    a = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                   ).json()["automations"][0]
    assert "הערך שבעמודה «תאריך התחלה»" in a["sentence"], a["sentence"]
    assert "«תאריך סיום»" in a["sentence"], a["sentence"]


def test_two_conditions_on_one_column_are_not_called_impossible(client, admin_id):
    """"התקציב הוא 1000" beside "התקציב הוא הערך שבעמודה «מאושר»" are both true
    of an item whose approved budget is 1000. Nothing at write time knows what
    the second one will hold, so nothing may call the pair a contradiction."""
    bid = _board(client, admin_id)
    budget = _col(client, bid, admin_id, type="number", title="תקציב")
    approved = _col(client, bid, admin_id, type="number", title="מאושר")
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}", json={
        "recipe_id": "created_set_priority",
        "config": {"a_priority": "high", "conditions": [
            {"kind": "column_is", "value": {"col": budget["id"], "type": "number",
                                            "value": 1000}},
            {"kind": "column_is", "value": {"col": budget["id"], "type": "number",
                                            "value": _ref(approved["id"], "number")}},
        ]}})
    assert r.status_code == 200, r.text


def test_a_compared_cell_holding_several_values_has_no_single_answer(client, admin_id):
    """A multi-select on the far side is not a comparison with each of them in
    turn. Taking the first would be the engine deciding which option the rule
    meant, so one value is a value and more than one holds the rule's fire."""
    bid = _board(client, admin_id)
    one = _col(client, bid, admin_id, type="dropdown", title="סוג פנייה",
               options=["תשתיות", "גינון"])
    two = _col(client, bid, admin_id, type="dropdown", title="סוג מאושר",
               options=["תשתיות", "גינון"])
    assert _add(client, bid, admin_id, _ref(two["id"], "dropdown"),
                one["id"], "dropdown").status_code == 200
    assert _fired(client, bid, admin_id,
                  {one["id"]: ["תשתיות"], two["id"]: ["תשתיות"]})
    assert not _fired(client, bid, admin_id,
                      {one["id"]: ["תשתיות"], two["id"]: ["תשתיות", "גינון"]})
