"""שיוך לעמודת אנשים — "שייך את X ל«מנהל פרויקט»".

A board has one built-in אחראים and it may also carry columns of type
people: מנהל פרויקט, רכזת, מפקח. "שייך את רות" could only ever mean the
built-in one, so a board that runs its work through a מנהל פרויקט column
could not be automated on it — except through the generic "עדכן את העמודה",
which reads as a cell being overwritten rather than as somebody being put on
the job, and which no "כאשר משויך אדם" trigger answers.

This is the same bargain the status column already struck, and deliberately
the same mechanism rather than a second one:

  · the column travels BESIDE the value under a derived key (`a_person_col`,
    `t_person_col`), never inside it, so nothing stored has to be rewritten;
  · an absent one means the board's own אחראים, which is what every rule
    written before columns could be named says — hence no migration;
  · the column is read off the board every time it is shown, so renaming it
    changes every sentence that mentions it with nothing re-saved.

One half of a sentence is never both kinds — a trigger is "כאשר הסטטוס
משתנה" or "כאשר משויך אדם", never the two at once — which is why the two
tables are read as one and the halves cannot collide.
"""
import pathlib
import subprocess
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import automations as recipes  # noqa: E402
import main as cityos_main  # noqa: E402
from models import Task, User  # noqa: E402

INDEX = ROOT / "frontend" / "index.html"


def _board(client, admin_id, who, name="לוח אנשים"):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": who, "role": "editor"})
    return bid


def _cols(client, bid, admin_id, titles, ctype="people"):
    cur = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
    r = client.patch(f"/api/boards/{bid}",
                     json={"actor_id": admin_id,
                           "columns": cur + [{"type": ctype, "title": t} for t in titles]})
    assert r.status_code == 200, r.text
    got = r.json()["columns"]
    return [next(c["id"] for c in got if c["title"] == t) for t in titles]


def _rule(client, bid, admin_id, recipe_id, config):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config})


def _item(client, bid, admin_id, title="פריט", cells=None):
    tid = client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                          "title": title}).json()["id"]
    if cells:
        assert client.patch(f"/api/tasks/{tid}",
                            json={"user_id": admin_id,
                                  "custom_fields": cells}).status_code == 200
    return tid


def _cell(tid, col):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        return (t.custom_fields or {}).get(col)


def _assignees(tid):
    with Session(cityos_main.engine) as db:
        return [u.id for u in db.query(Task).filter(Task.id == tid).first().assignees]


def _status(tid):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        return cityos_main._task_status_key(t)


# ── the action writes the column it names ─────────────────────────────────
def test_a_rule_assigns_into_the_column_it_names(client, admin_id, member_id):
    bid = _board(client, admin_id, member_id)
    pm, rk = _cols(client, bid, admin_id, ["מנהל פרויקט", "רכזת"])
    r = _rule(client, bid, admin_id, "created_assign_person",
              {"a_person": member_id, "a_person_col": pm})
    assert r.status_code == 200, r.text
    tid = _item(client, bid, admin_id)
    assert _cell(tid, pm) == [member_id]
    assert _cell(tid, rk) is None, "it wrote a column the rule never named"
    assert _assignees(tid) == [], "it also assigned the built-in אחראים"


def test_silence_still_means_the_boards_own_assignees(client, admin_id, member_id):
    """No migration, and that is the point of the column travelling beside the
    value: every rule written before this means exactly what it meant."""
    bid = _board(client, admin_id, member_id)
    (pm,) = _cols(client, bid, admin_id, ["מנהל פרויקט"])
    assert _rule(client, bid, admin_id, "created_assign_person",
                 {"a_person": member_id}).status_code == 200
    tid = _item(client, bid, admin_id)
    assert _assignees(tid) == [member_id]
    assert _cell(tid, pm) is None


def test_removing_takes_the_person_out_of_that_column_only(client, admin_id, member_id):
    """"הסר את X" is an extra action — the catalog pairs no trigger with it as
    a rule's own — so it carries its column under the bare key an extra
    action's values use, which is the same key the engine reads whichever
    half it came from."""
    bid = _board(client, admin_id, member_id)
    pm, rk = _cols(client, bid, admin_id, ["מנהל פרויקט", "רכזת"])
    r = _rule(client, bid, admin_id, "created_set_status",
              {"a_status": "in_progress",
               recipes.ACTIONS_KEY: [{"key": "unassign_person",
                                      "values": {"person": member_id,
                                                 "person_col": pm}}]})
    assert r.status_code == 200, r.text
    tid = client.post("/api/tasks",
                      json={"board_id": bid, "user_id": admin_id, "title": "ב",
                            "custom_fields": {pm: [member_id],
                                              rk: [member_id]}}).json()["id"]
    assert _cell(tid, pm) == [], "the named column kept the person"
    assert _cell(tid, rk) == [member_id], "it emptied a column it was not about"


def test_a_name_imported_without_an_account_is_left_alone(client, admin_id, member_id):
    """A people cell may also hold a bare name, imported from a board that had
    no account for that person. A rule writing the cell must not delete one —
    it is somebody's data, and the rule was not asked about it."""
    bid = _board(client, admin_id, member_id)
    (pm,) = _cols(client, bid, admin_id, ["מנהל פרויקט"])
    assert _rule(client, bid, admin_id, "created_assign_person",
                 {"a_person": member_id, "a_person_col": pm}).status_code == 200
    tid = client.post("/api/tasks",
                      json={"board_id": bid, "user_id": admin_id, "title": "ג",
                            "custom_fields": {pm: ["רות מהייבוא"]}}).json()["id"]
    assert _cell(tid, pm) == [member_id, "רות מהייבוא"], _cell(tid, pm)


# ── the trigger listens to the column it names ────────────────────────────
def test_a_trigger_hears_only_the_column_it_names(client, admin_id, member_id):
    bid = _board(client, admin_id, member_id)
    pm, rk = _cols(client, bid, admin_id, ["מנהל פרויקט", "רכזת"])
    assert _rule(client, bid, admin_id, "assigned_set_status",
                 {"t_person_col": rk, "a_status": "done"}).status_code == 200
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id,
                                            "custom_fields": {pm: [member_id]}})
    assert _status(tid) != "done", "a rule about רכזת fired on מנהל פרויקט"
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id,
                                            "custom_fields": {rk: [member_id]}})
    assert _status(tid) == "done"


def test_a_trigger_on_the_boards_own_assignees_is_not_woken_by_a_column(
        client, admin_id, member_id):
    """The other direction, and the one that would have been a silent
    regression: a rule written before columns could be named must not start
    firing on a column it never heard of."""
    bid = _board(client, admin_id, member_id)
    (pm,) = _cols(client, bid, admin_id, ["מנהל פרויקט"])
    assert _rule(client, bid, admin_id, "assigned_set_status",
                 {"a_status": "done"}).status_code == 200
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id,
                                            "custom_fields": {pm: [member_id]}})
    assert _status(tid) != "done", "a column assignment woke the built-in rule"
    client.post(f"/api/tasks/{tid}/assignees",
                json={"actor_id": admin_id, "user_id": member_id})
    assert _status(tid) == "done"


def test_it_fires_however_the_name_got_into_the_cell(client, admin_id, member_id):
    """Typed in by a person, or written by another rule — "כאשר משויך אדם
    ל«מנהל פרויקט»" is about the item, not about who did it."""
    bid = _board(client, admin_id, member_id)
    (pm,) = _cols(client, bid, admin_id, ["מנהל פרויקט"])
    assert _rule(client, bid, admin_id, "created_assign_person",
                 {"a_person": member_id, "a_person_col": pm}).status_code == 200
    assert _rule(client, bid, admin_id, "assigned_set_status",
                 {"t_person_col": pm, "a_status": "done"}).status_code == 200
    tid = _item(client, bid, admin_id)
    assert _cell(tid, pm) == [member_id]
    assert _status(tid) == "done", "one rule's assignment did not reach the other"


# ── what the rule reads as ────────────────────────────────────────────────
def test_the_sentence_names_the_column_and_follows_a_rename(client, admin_id,
                                                            member_id):
    bid = _board(client, admin_id, member_id)
    (pm,) = _cols(client, bid, admin_id, ["מנהל פרויקט"])
    r = _rule(client, bid, admin_id, "created_assign_person",
              {"a_person": member_id, "a_person_col": pm})
    assert "ל«מנהל פרויקט»" in r.json()["sentence"], r.json()["sentence"]
    plain = _rule(client, bid, admin_id, "created_assign_person",
                  {"a_person": member_id})
    assert "ל«" not in plain.json()["sentence"].split("שייך את")[-1], \
        plain.json()["sentence"]

    cols = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
    for c in cols:
        if c["id"] == pm:
            c["title"] = "מוביל"
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    d = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
    said = [x["sentence"] for x in d["automations"] if "שייך" in x["sentence"]]
    assert any("ל«מוביל»" in x for x in said), said


def test_a_half_offers_one_kind_of_column_and_the_two_never_collide():
    """A trigger is "כאשר הסטטוס משתנה" or "כאשר משויך אדם", never both — so
    one table of alternative wordings serves both, and a recipe can name a
    people column on one half and a status column on the other."""
    r = recipes.recipe("assigned_set_status")
    assert recipes.col_kind_of(r, "t") == "people"
    assert recipes.col_kind_of(r, "a") == "status"
    assert recipes.col_key_of(r, "t") == "t_person_col"
    assert recipes.col_key_of(r, "a") == "a_status_col"
    # …and a half that names none says so
    n = recipes.recipe("created_notify_person")
    assert recipes.col_kind_of(n, "t") == "" and recipes.col_key_of(n, "t") == ""
    # every people wording has a {col} to put it in
    for k, t in recipes.PEOPLE_COL_TEXT.items():
        assert "{col}" in t, k
    assert not set(recipes.STATUS_COL_TEXT) & set(recipes.PEOPLE_COL_TEXT)


def test_the_catalog_tells_the_picker_which_list_to_offer(client, admin_id):
    d = client.get("/api/automations/recipes").json()
    by = {x["id"]: x for x in d["recipes"]}
    p = by["created_assign_person"]["sentence_parts"]
    assert p["action_col_kind"] == "people", p
    assert "{a_person_col}" in p["action_col"], p
    q = by["assigned_set_status"]["sentence_parts"]
    assert q["trigger_col_kind"] == "people" and q["action_col_kind"] == "status", q
    # and a half that names none offers nothing
    n = by["created_notify_person"]["sentence_parts"]
    assert n["action_col_kind"] == "" and n["action_col"] == "", n


# ── a column that is not there ────────────────────────────────────────────
def test_a_column_the_board_does_not_have_is_refused_at_the_save(client, admin_id,
                                                                 member_id):
    bid = _board(client, admin_id, member_id)
    r = _rule(client, bid, admin_id, "created_assign_person",
              {"a_person": member_id, "a_person_col": "col_nope"})
    assert r.status_code == 400, r.text
    assert "עמודת האנשים" in r.json()["detail"], r.json()


def test_nor_is_a_column_of_the_wrong_kind(client, admin_id, member_id):
    bid = _board(client, admin_id, member_id)
    (txt,) = _cols(client, bid, admin_id, ["הערה"], ctype="text")
    r = _rule(client, bid, admin_id, "created_assign_person",
              {"a_person": member_id, "a_person_col": txt})
    assert r.status_code == 400, r.text


def test_a_column_deleted_later_is_reported_rather_than_silently_dead(
        client, admin_id, member_id):
    """The rule cannot be refused retroactively, so it is flagged: the event
    it waits for stops being emitted and it would otherwise go on looking
    active for ever."""
    bid = _board(client, admin_id, member_id)
    (pm,) = _cols(client, bid, admin_id, ["מנהל פרויקט"])
    rid = _rule(client, bid, admin_id, "assigned_set_status",
                {"t_person_col": pm, "a_status": "done"}).json()["id"]
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if c["id"] != pm]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    v = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "assigned_set_status",
                          "config": {"t_person_col": pm, "a_status": "done"}})
    assert v.status_code == 200, v.text
    assert any("עמודת האנשים" in b for b in v.json().get("blockers") or []), v.json()
    assert rid


# ── the browser asks the same question ────────────────────────────────────
def test_the_browser_offers_the_column_before_the_value():
    src = INDEX.read_text(encoding="utf-8")
    i = src.index("  _peopleSources(){")
    body = src[i:src.index("\n  },", i)]
    assert "'אחראים'" in body, "the board's own assignees are not offered"
    assert "_peopleCols()" in body
    # the blank is shown from the start on a people half, because the trigger
    # has no blank of its own to press
    assert "const peopleOn=side=>this._colKind(side)==='people'" in src
    # …and only where there is a choice to make
    assert "this._peopleCols().length>0" in src
    # unset reads as the real answer it stands for, not as an empty prompt
    assert "if(f.type==='people_col') return mk(v?this._colCell(v).label:'אחראים');" in src
    # the choice is sent, and an empty one is not — empty IS the built-in
    assert "config[side+'_person_col']=col;" in src


def test_the_browser_half():
    """The two steps as they actually appear, run out of index.html."""
    r = subprocess.run(["node", str(ROOT / "tests" / "frontend" /
                                    "automation_assign_to_a_people_column.mjs")],
                       capture_output=True, text=True)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
