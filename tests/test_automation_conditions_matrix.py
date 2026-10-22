"""Group — תנאים ומטריצת שדות: one group, typed operators, honest nulls.

  · one condition group, all AND or all OR, with nowhere to mix them;
  · the operators each kind of field offers, and a type-safe refusal of the
    ones it does not;
  · a value nobody filled in is not zero and not an empty string;
  · a condition that does not hold is a SKIP and never a failure;
  · the field matrix, and automation-capabilities as the one place that says
    what this engine can be asked.
"""
from sqlalchemy.orm import Session
import automations as recipes
import main as cityos_main
from models import Automation, Task


def _board(client, admin_id, name="לוח תנאים"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _col(client, bid, admin_id, **spec):
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    col = {"id": "col_" + spec["type"][:6] + str(len(cols)), **spec}
    cols.append(col)
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    assert r.status_code == 200, r.text
    return col


def _add(client, bid, admin_id, conds, op=None, **extra):
    cfg = {"a_priority": "high", "conditions": conds}
    if op:
        cfg["conditions_op"] = op
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": "created_set_priority", "config": cfg, **extra})


def _cond(col, col_type, op=None, value=None, value2=None, match=None, kind="column_is"):
    v = {"col": col, "type": col_type}
    if op:
        v["op"] = op
    if value is not None:
        v["value"] = value
    if value2 is not None:
        v["value2"] = value2
    if match:
        v["match"] = match
    return {"kind": kind, "value": v}


def _item(client, bid, admin_id, fields=None, **extra):
    return client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                           "user_id": admin_id,
                                           "custom_fields": fields or {}, **extra}
                       ).json()["id"]


def _fired(client, bid, admin_id, fields=None, **extra):
    tid = _item(client, bid, admin_id, fields, **extra)
    with Session(cityos_main.engine) as db:
        return cityos_main._task_priority_key(
            db.query(Task).filter(Task.id == tid).first()) == "high"


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]


# ── one group, and nowhere to mix ──────────────────────────────────────────

def test_conditions_are_all_of_them_by_default(client, admin_id):
    bid = _board(client, admin_id, "לוח AND")
    a = _col(client, bid, admin_id, type="number", title="תקציב")
    b = _col(client, bid, admin_id, type="text", title="אזור")
    assert _add(client, bid, admin_id,
                [_cond(a["id"], "number", "gt", 100),
                 _cond(b["id"], "text", "eq", "צפון")]).status_code == 200
    assert _fired(client, bid, admin_id, {a["id"]: 500, b["id"]: "צפון"})
    assert not _fired(client, bid, admin_id, {a["id"]: 500, b["id"]: "דרום"})
    assert not _fired(client, bid, admin_id, {a["id"]: 5, b["id"]: "צפון"})


def test_or_takes_any_one_of_them(client, admin_id):
    bid = _board(client, admin_id, "לוח OR")
    a = _col(client, bid, admin_id, type="number", title="תקציב")
    b = _col(client, bid, admin_id, type="text", title="אזור")
    r = _add(client, bid, admin_id,
             [_cond(a["id"], "number", "gt", 100), _cond(b["id"], "text", "eq", "צפון")],
             op="or")
    assert r.status_code == 200, r.text
    assert r.json()["config"]["conditions_op"] == "or"
    assert _fired(client, bid, admin_id, {a["id"]: 500, b["id"]: "דרום"})
    assert _fired(client, bid, admin_id, {a["id"]: 5, b["id"]: "צפון"})
    assert not _fired(client, bid, admin_id, {a["id"]: 5, b["id"]: "דרום"})


def test_the_sentence_says_which_group_it_is(client, admin_id):
    bid = _board(client, admin_id, "לוח משפט")
    a = _col(client, bid, admin_id, type="text", title="אזור")
    b = _col(client, bid, admin_id, type="text", title="סוג")
    got = _add(client, bid, admin_id,
               [_cond(a["id"], "text", "eq", "צפון"), _cond(b["id"], "text", "eq", "דחוף")],
               op="or").json()
    assert " או " in got["sentence"] and " וגם " not in got["sentence"]


def test_or_over_one_condition_is_refused(client, admin_id):
    """"לפחות תנאי אחד מסוג OR" takes two to mean anything."""
    bid = _board(client, admin_id, "לוח OR יחיד")
    a = _col(client, bid, admin_id, type="text", title="אזור")
    r = _add(client, bid, admin_id, [_cond(a["id"], "text", "eq", "צפון")], op="or")
    assert r.status_code == 400 and "שני תנאים" in r.json()["detail"]


def test_an_operator_that_is_not_and_or_or_is_refused(client, admin_id):
    bid = _board(client, admin_id, "לוח אופרטור קבוצה")
    a = _col(client, bid, admin_id, type="text", title="אזור")
    b = _col(client, bid, admin_id, type="text", title="סוג")
    r = _add(client, bid, admin_id,
             [_cond(a["id"], "text", "eq", "צפון"), _cond(b["id"], "text", "eq", "דחוף")],
             op="xor")
    assert r.status_code == 400 and "AND" in r.json()["detail"]


def test_there_is_one_group_and_so_nowhere_to_mix(client, admin_id):
    """The structure IS the rule: a rule carries one list of conditions and one
    operator over it, so "א וגם ב או ג" cannot be expressed at all."""
    assert recipes.CONDITION_GROUP_OPS == ("and", "or")
    assert recipes.CONDITION_GROUP_KEY == "conditions_op"
    bid = _board(client, admin_id, "לוח קבוצה אחת")
    a = _col(client, bid, admin_id, type="text", title="אזור")
    b = _col(client, bid, admin_id, type="text", title="סוג")
    got = _add(client, bid, admin_id,
               [_cond(a["id"], "text", "eq", "צפון"), _cond(b["id"], "text", "eq", "דחוף")],
               op="or").json()
    assert isinstance(got["config"]["conditions"], list)
    assert got["config"]["conditions_op"] == "or"


# ── the operators, per kind ────────────────────────────────────────────────

def test_a_number_column_offers_the_number_questions(client, admin_id):
    bid = _board(client, admin_id, "לוח מספרים")
    c = _col(client, bid, admin_id, type="number", title="תקציב")
    for op, v, v2, hit, miss in (("gt", 100, None, 500, 50),
                                 ("lt", 100, None, 50, 500),
                                 ("ne", 100, None, 50, 100)):
        b2 = _board(client, admin_id, f"לוח {op}")
        col = _col(client, b2, admin_id, type="number", title="תקציב")
        assert _add(client, b2, admin_id,
                    [_cond(col["id"], "number", op, v, v2)]).status_code == 200
        assert _fired(client, b2, admin_id, {col["id"]: hit}), op
        assert not _fired(client, b2, admin_id, {col["id"]: miss}), op


def test_between_takes_two_values(client, admin_id):
    bid = _board(client, admin_id, "לוח טווח")
    c = _col(client, bid, admin_id, type="number", title="תקציב")
    r = _add(client, bid, admin_id, [_cond(c["id"], "number", "between", 100, 200)])
    assert r.status_code == 200, r.text
    assert _fired(client, bid, admin_id, {c["id"]: 150})
    assert not _fired(client, bid, admin_id, {c["id"]: 500})
    # and a range with only one end is refused
    bad = _add(client, _board(client, admin_id, "לוח טווח חסר"), admin_id,
               [_cond(c["id"], "number", "between", 100)])
    assert bad.status_code == 400


def test_text_can_be_asked_whether_it_contains(client, admin_id):
    bid = _board(client, admin_id, "לוח מכיל")
    c = _col(client, bid, admin_id, type="text", title="הערה")
    assert _add(client, bid, admin_id, [_cond(c["id"], "text", "has", "דחוף")]
                ).status_code == 200
    assert _fired(client, bid, admin_id, {c["id"]: "טיפול דחוף מאוד"})
    assert not _fired(client, bid, admin_id, {c["id"]: "טיפול רגיל"})


def test_a_people_column_can_be_asked_whether_it_includes_a_user(client, admin_id,
                                                                  guinea_id):
    bid = _board(client, admin_id, "לוח אנשים")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    c = _col(client, bid, admin_id, type="people", title="מלווה")
    assert _add(client, bid, admin_id,
                [_cond(c["id"], "people", "has", guinea_id)]).status_code == 200
    assert _fired(client, bid, admin_id, {c["id"]: [guinea_id]})
    assert not _fired(client, bid, admin_id, {c["id"]: [admin_id]})


def test_empty_and_filled_are_about_the_cell_itself(client, admin_id):
    bid = _board(client, admin_id, "לוח ריק")
    c = _col(client, bid, admin_id, type="text", title="הערה")
    assert _add(client, bid, admin_id, [_cond(c["id"], "text", "empty")]).status_code == 200
    assert _fired(client, bid, admin_id, {})
    assert not _fired(client, bid, admin_id, {c["id"]: "משהו"})


def test_an_operator_the_kind_does_not_offer_is_refused(client, admin_id):
    """Type-safe: "גדול מ" over a text column is a question with no answer,
    and it is refused when it is written rather than skipped for ever."""
    bid = _board(client, admin_id, "לוח אופרטור שגוי")
    c = _col(client, bid, admin_id, type="text", title="הערה")
    r = _add(client, bid, admin_id, [_cond(c["id"], "text", "gt", 5)])
    assert r.status_code == 400 and "אופרטור" in r.json()["detail"]


def test_a_value_of_the_wrong_type_is_refused(client, admin_id):
    bid = _board(client, admin_id, "לוח ערך שגוי")
    c = _col(client, bid, admin_id, type="number", title="תקציב")
    r = _add(client, bid, admin_id, [_cond(c["id"], "number", "gt", "גבוה")])
    assert r.status_code == 400 and "מספר" in r.json()["detail"]


# ── a cell nobody filled in ────────────────────────────────────────────────

def test_a_missing_number_is_not_zero(client, admin_id):
    """"ערך חסר אינו מומר אוטומטית לאפס" — "קטן מ-100" must not be true of a
    budget nobody has written yet."""
    bid = _board(client, admin_id, "לוח חסר מספר")
    c = _col(client, bid, admin_id, type="number", title="תקציב")
    _add(client, bid, admin_id, [_cond(c["id"], "number", "lt", 100)])
    assert not _fired(client, bid, admin_id, {})
    assert _fired(client, bid, admin_id, {c["id"]: 50})
    # and zero IS a number: a budget of zero is a budget
    assert _fired(client, bid, admin_id, {c["id"]: 0})


def test_a_missing_text_is_not_an_empty_string(client, admin_id):
    bid = _board(client, admin_id, "לוח חסר טקסט")
    c = _col(client, bid, admin_id, type="text", title="הערה")
    _add(client, bid, admin_id, [_cond(c["id"], "text", "eq", "")], )
    # an empty value is refused outright, so the rule above never saved — the
    # question "is it the empty string" is asked with "ריק" instead
    rows = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                      ).json()["automations"]
    assert rows == []


def test_a_missing_value_does_not_satisfy_a_comparison(client, admin_id):
    bid = _board(client, admin_id, "לוח חסר השוואה")
    c = _col(client, bid, admin_id, type="text", title="הערה")
    _add(client, bid, admin_id, [_cond(c["id"], "text", "has", "דחוף")])
    assert not _fired(client, bid, admin_id, {})


# ── a condition that does not hold is a skip ───────────────────────────────

def test_an_unmet_condition_is_a_skip_and_not_a_failure(client, admin_id):
    bid = _board(client, admin_id, "לוח דילוג")
    c = _col(client, bid, admin_id, type="number", title="תקציב")
    _add(client, bid, admin_id, [_cond(c["id"], "number", "gt", 100)])
    _item(client, bid, admin_id, {c["id"]: 5})
    runs = _runs(client, bid, admin_id)
    assert runs and runs[0]["outcome"] == "skipped", runs[:1]
    assert runs[0]["outcome"] != "failed"
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.board_id == bid).first()
        assert a.status == "active" and (a.fail_count or 0) == 0


def test_an_or_group_that_nothing_satisfies_names_the_group(client, admin_id):
    bid = _board(client, admin_id, "לוח דילוג OR")
    a = _col(client, bid, admin_id, type="text", title="אזור")
    b = _col(client, bid, admin_id, type="text", title="סוג")
    _add(client, bid, admin_id,
         [_cond(a["id"], "text", "eq", "צפון"), _cond(b["id"], "text", "eq", "דחוף")],
         op="or")
    _item(client, bid, admin_id, {a["id"]: "דרום", b["id"]: "רגיל"})
    runs = _runs(client, bid, admin_id)
    assert runs[0]["outcome"] == "skipped"
    assert "אף תנאי" in runs[0]["reason"] and " או " in runs[0]["reason"], runs[0]["reason"]


# ── the matrix ─────────────────────────────────────────────────────────────

def test_the_matrix_says_what_each_kind_of_field_may_be(client):
    m = recipes.FIELD_MATRIX
    # מראה — a condition only, never a trigger and never written
    assert m["mirror"] == {**m["mirror"], "trigger": False, "condition": True, "action": False}
    # קובץ — asked only whether it is there
    assert recipes.field_ops("files") == ("empty", "filled")
    # שדות מערכת and a formula — read only
    for t in ("item_id", "created_at", "created_by", "formula"):
        assert m[t]["trigger"] is False and m[t]["action"] is False and m[t]["condition"]
    # קישור — all three
    assert m["connect"]["trigger"] and m["connect"]["condition"] and m["connect"]["action"]
    # and every entry says what governs it
    assert all(v["rule"] for v in m.values())


def test_a_type_outside_the_matrix_is_not_available(client, admin_id):
    bid = _board(client, admin_id, "לוח סוג לא מוכר")
    r = _add(client, bid, admin_id, [_cond("col_x", "something_new", "eq", "x")])
    assert r.status_code == 400
    assert recipes.column_kind("something_new") is None
    assert recipes.field_ops("something_new") == ()


def test_a_file_column_can_only_be_asked_whether_it_is_there(client, admin_id):
    bid = _board(client, admin_id, "לוח קבצים")
    c = _col(client, bid, admin_id, type="files", title="מסמכים")
    assert _add(client, bid, admin_id, [_cond(c["id"], "files", "filled")]).status_code == 200
    bad = _add(client, _board(client, admin_id, "לוח קבצים ב"), admin_id,
               [_cond(c["id"], "files", "eq", "x")])
    assert bad.status_code == 400


def test_a_connect_column_is_asked_about_the_link(client, admin_id):
    far = _board(client, admin_id, "לוח יעד לקישור")
    bid = _board(client, admin_id, "לוח קישור")
    c = _col(client, bid, admin_id, type="connect", title="קישור",
             connect={"board_ids": [far], "multi": True})
    far_item = _item(client, far, admin_id)
    assert _add(client, bid, admin_id, [_cond(c["id"], "connect", "linked")]).status_code == 200
    assert _fired(client, bid, admin_id, {c["id"]: [far_item]})
    assert not _fired(client, bid, admin_id, {})


def test_a_connect_column_can_name_the_item(client, admin_id):
    far = _board(client, admin_id, "יעד פריט מסוים")
    bid = _board(client, admin_id, "מקור פריט מסוים")
    c = _col(client, bid, admin_id, type="connect", title="קישור",
             connect={"board_ids": [far], "multi": True})
    one, two = _item(client, far, admin_id), _item(client, far, admin_id)
    _add(client, bid, admin_id, [_cond(c["id"], "connect", "linked", one)])
    assert _fired(client, bid, admin_id, {c["id"]: [one]})
    assert not _fired(client, bid, admin_id, {c["id"]: [two]})


# ── a mirror over several items ────────────────────────────────────────────

def _mirror_board(client, admin_id, name):
    far = _board(client, admin_id, name + " יעד")
    bid = _board(client, admin_id, name)
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    cols += [{"id": "col_link", "type": "connect", "title": "קישור",
              "connect": {"board_ids": [far], "multi": True}},
             {"id": "col_mir", "type": "mirror", "title": "שם אצלם",
              "mirror_of": {"connect": "col_link", "field": "title"}}]
    client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    return far, bid


def test_a_mirror_matches_on_any_of_the_linked_items_by_default(client, admin_id):
    far, bid = _mirror_board(client, admin_id, "לוח מראה כלשהו")
    hit = client.post("/api/tasks", json={"board_id": far, "title": "מתאים",
                                          "user_id": admin_id}).json()["id"]
    other = client.post("/api/tasks", json={"board_id": far, "title": "אחר",
                                            "user_id": admin_id}).json()["id"]
    r = _add(client, bid, admin_id, [_cond("col_mir", "mirror", "eq", "מתאים")])
    assert r.status_code == 200, r.text
    assert r.json()["config"]["conditions"][0]["value"]["match"] == "any"
    assert _fired(client, bid, admin_id, {"col_link": [hit, other]})
    assert not _fired(client, bid, admin_id, {"col_link": [other]})


def test_a_mirror_can_be_asked_for_all_of_them(client, admin_id):
    far, bid = _mirror_board(client, admin_id, "לוח מראה כולם")
    one = client.post("/api/tasks", json={"board_id": far, "title": "מתאים",
                                          "user_id": admin_id}).json()["id"]
    two = client.post("/api/tasks", json={"board_id": far, "title": "מתאים",
                                          "user_id": admin_id}).json()["id"]
    odd = client.post("/api/tasks", json={"board_id": far, "title": "אחר",
                                          "user_id": admin_id}).json()["id"]
    _add(client, bid, admin_id,
         [_cond("col_mir", "mirror", "eq", "מתאים", match="all")])
    assert _fired(client, bid, admin_id, {"col_link": [one, two]})
    assert not _fired(client, bid, admin_id, {"col_link": [one, odd]})


def test_a_mirror_reflecting_nothing_satisfies_neither(client, admin_id):
    far, bid = _mirror_board(client, admin_id, "לוח מראה ריק")
    for match in ("any", "all"):
        b2 = _mirror_board(client, admin_id, f"לוח מראה ריק {match}")[1]
        _add(client, b2, admin_id,
             [_cond("col_mir", "mirror", "eq", "מתאים", match=match)])
        assert not _fired(client, b2, admin_id, {}), match


def test_a_mirror_a_reader_may_not_see_is_shown_as_protected(client, admin_id, guinea_id):
    """"מידע ממקור שאין לצופה הרשאה אליו יוצג כמידע מוגן" — withheld and said
    to be withheld, because a reader who thinks a cell is blank draws the wrong
    conclusion about why the rule did not fire."""
    far, bid = _mirror_board(client, admin_id, "לוח מראה מוגן")
    hidden = client.post("/api/tasks", json={"board_id": far, "title": "סודי",
                                             "user_id": admin_id}).json()["id"]
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    a = _add(client, bid, admin_id, [_cond("col_mir", "mirror", "eq", "סודי")]).json()
    tid = _item(client, bid, admin_id, {"col_link": [hidden]})

    mine = client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}",
                       json={"task_id": tid}).json()
    assert mine["conditions"][0]["actual"] == "סודי"
    theirs = client.post(f"/api/automations/{a['id']}/test?user_id={guinea_id}",
                         json={"task_id": tid}).json()
    assert "מידע מוגן" in theirs["conditions"][0]["actual"], theirs["conditions"][0]
    assert "סודי" not in theirs["conditions"][0]["actual"]


# ── automation-capabilities ────────────────────────────────────────────────

def test_the_capabilities_service_answers_what_the_engine_can_do(client, admin_id):
    d = client.get(f"/api/automation-capabilities?user_id={admin_id}").json()
    assert {f["type"] for f in d["fields"]} == set(recipes.FIELD_MATRIX)
    assert d["group_operators"] == ["and", "or"]
    assert d["mirror_match"] == ["any", "all"] and d["mirror_match_default"] == "any"
    assert d["null_semantics"]["no_coercion"] is True
    assert d["null_semantics"]["unmet_condition_is"] == "skipped"
    # every operator the spec names is in the table somewhere
    all_ops = {o for ops in d["operators"].values() for o in ops}
    for op in ("eq", "ne", "has", "nhas", "empty", "filled", "gt", "lt", "between",
               "before", "after", "linked", "not_linked"):
        assert op in all_ops, op
    assert all(d["operator_labels"].get(o) for o in all_ops)


def test_the_capabilities_answer_for_one_board_s_own_columns(client, admin_id):
    bid = _board(client, admin_id, "לוח יכולות")
    _col(client, bid, admin_id, type="text", title="הערה")
    _col(client, bid, admin_id, type="mirror", title="מראה",
         mirror_of={"connect": "col_link", "field": "title"})
    d = client.get(f"/api/automation-capabilities?board_id={bid}&user_id={admin_id}").json()
    by = {c["title"]: c for c in d["columns"]}
    assert by["הערה"]["trigger"] is True and by["הערה"]["condition"] is True
    assert by["מראה"]["trigger"] is False and by["מראה"]["condition"] is True
    assert by["מראה"]["action"] is False


def test_a_column_of_a_type_nobody_defined_is_marked_unavailable(client, admin_id):
    bid = _board(client, admin_id, "לוח סוג חדש")
    with Session(cityos_main.engine) as db:
        b = db.query(cityos_main.Board).filter(cityos_main.Board.id == bid).first()
        b.settings = {**(b.settings or {}),
                      "columns": [{"id": "col_x", "type": "hologram", "title": "חדש"}]}
        db.commit()
    d = client.get(f"/api/automation-capabilities?board_id={bid}&user_id={admin_id}").json()
    col = d["columns"][0]
    assert col["known"] is False and col["condition"] is False and col["operators"] == []
    assert "בדיקת תאימות" in col["note"]


def test_the_capabilities_follow_the_viewing_permission(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח יכולות פרטי")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "viewer"})
    assert client.get(f"/api/automation-capabilities?board_id={bid}&user_id={member_id}"
                      ).status_code == 403
    # the matrix itself is not board data and is readable
    assert client.get(f"/api/automation-capabilities?user_id={member_id}"
                      ).status_code == 200
