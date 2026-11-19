"""עמודת מראה → עמודת אנשים — "שייך את מי שמופיע בעמודת המראה".

A mirror shows a field of a LINKED item, and what it shows is TEXT: whatever
the source cell displays. Where the source is a people column that text is a
person's NAME — readable and nothing else. It cannot be filtered on as a
person, it does not put a face on the row, and no rule on this board could act
on it, because the board has no idea there is an account behind it.

«שייך את מי שמופיע בעמודת המראה» is the action that closes that gap: read the
mirror, match each name back to an account ON THIS BOARD, and write it into
one of the board's own people columns — or its built-in אחראים when the rule
names none, which is the same bargain «שייך את X ל«מנהל פרויקט»» already
strikes.

What this file pins:

  · the cell that comes out is a real assignment — ids, not text — so the
    filters, the avatars and the "כאשר משויך אדם" rules all see it;
  · a name is matched inside ONE BOARD and never across the organisation,
    and a name two accounts on the board answer to is refused rather than
    guessed at;
  · "בנוסף" is what silence means, and "במקום" never empties a cell — an
    empty mirror is a rule that skips, not a rule that clears a column;
  · a mirror the rule can no longer read blocks it instead of letting it look
    active while it silently skips for ever.
"""
import pathlib
import subprocess
import sys

from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import automations as recipes  # noqa: E402
import main as cityos_main  # noqa: E402
from models import Task  # noqa: E402

from conftest import join_primary_env  # noqa: E402

INDEX = ROOT / "frontend" / "index.html"
AS = lambda uid: {"X-CityOS-User": str(uid)}


# ── the board in front of the rule ────────────────────────────────────────
def _board(client, admin_id, name, members=()):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    for uid in members:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": "editor"})
    return bid


def _cols(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]


def _add_cols(client, bid, admin_id, more):
    r = client.patch(f"/api/boards/{bid}",
                     json={"actor_id": admin_id,
                           "columns": _cols(client, bid, admin_id) + more},
                     headers=AS(admin_id))
    assert r.status_code == 200, r.text
    got = r.json()["columns"]
    return [next(c["id"] for c in got if c["title"] == m["title"]) for m in more]


def _item(client, bid, admin_id, title="פריט", cells=None):
    tid = client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                          "title": title}).json()["id"]
    if cells:
        assert client.patch(f"/api/tasks/{tid}?user_id={admin_id}",
                            json={"custom_fields": cells},
                            headers=AS(admin_id)).status_code == 200
    return tid


def _cell(tid, col):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        return (t.custom_fields or {}).get(col)


def _assignees(tid):
    with Session(cityos_main.engine) as db:
        return [u.id for u in db.query(Task).filter(Task.id == tid).first().assignees]


def _rule(client, bid, admin_id, recipe_id, config):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config})


def _link(client, tid, connect_id, ids, admin_id):
    return client.patch(f"/api/tasks/{tid}?user_id={admin_id}",
                        json={"custom_fields": {connect_id: ids}}, headers=AS(admin_id))


def _stage(client, admin_id, who, name, source_cells=None, source_type="people"):
    """Two boards, a link between them and a mirror over it.

    `src` carries the column whose value the mirror shows; `dst` carries the
    connect column, the mirror, and the local people column the rule fills.
    """
    src = _board(client, admin_id, f"מקור {name}", [who])
    (s_col,) = _add_cols(client, src, admin_id,
                         [{"type": source_type, "title": "אחראי במקור"}])
    dst = _board(client, admin_id, f"יעד {name}", [who])
    (conn,) = _add_cols(client, dst, admin_id,
                        [{"type": "connect", "title": "המקור",
                          "connect": {"board_ids": [src], "multiple": True,
                                      "two_way": False}}])
    mir, pm, rk = _add_cols(client, dst, admin_id, [
        {"type": "mirror", "title": "אחראי מהמקור",
         "mirror_of": {"connect": conn, "field": s_col}},
        {"type": "people", "title": "מנהל פרויקט"},
        {"type": "people", "title": "רכזת"}])
    far = _item(client, src, admin_id, "פריט מקור",
                {s_col: source_cells} if source_cells is not None else None)
    return {"src": src, "dst": dst, "s_col": s_col, "conn": conn,
            "mir": mir, "pm": pm, "rk": rk, "far": far}


# ── the name becomes a person ─────────────────────────────────────────────
def test_the_name_in_the_mirror_becomes_the_account_behind_it(client, admin_id, member_id):
    """The whole feature in one rule: the mirror shows "בודק חבר", and what
    lands in «מנהל פרויקט» is that person's id — not the four letters."""
    s = _stage(client, admin_id, member_id, "m1", [member_id])
    assert _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
                 {"a_mirror": s["mir"], "a_person_col": s["pm"]}).status_code == 200
    near = _item(client, s["dst"], admin_id, "פריט יעד")
    assert _link(client, near, s["conn"], [s["far"]], admin_id).status_code == 200
    assert _cell(near, s["pm"]) == [member_id], _cell(near, s["pm"])
    assert _cell(near, s["rk"]) is None, "it wrote a column the rule never named"
    assert _assignees(near) == [], "it also assigned the board's built-in אחראים"


def test_a_saved_rule_names_its_mirror_and_column_by_title_not_id(client, admin_id, member_id):
    """The rule list reads the sentence off the server, and the label lookup
    there knew a column and a connect column but not a mirror — so a saved
    rule read "שבעמודת המראה col_…" where the builder had shown the title."""
    s = _stage(client, admin_id, member_id, "m-label", [member_id])
    r = _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
              {"a_mirror": s["mir"], "a_person_col": s["pm"]})
    assert r.status_code == 200, r.text
    said = r.json()["sentence"]
    assert "אחראי מהמקור" in said, said
    assert "מנהל פרויקט" in said, said
    assert s["mir"] not in said and s["pm"] not in said, said


def test_without_a_column_it_fills_the_boards_own_assignees(client, admin_id, member_id):
    """Silence means the built-in, exactly as it does for «שייך את X»."""
    s = _stage(client, admin_id, member_id, "m2", [member_id])
    assert _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
                 {"a_mirror": s["mir"]}).status_code == 200
    near = _item(client, s["dst"], admin_id, "פריט יעד")
    _link(client, near, s["conn"], [s["far"]], admin_id)
    assert _assignees(near) == [member_id]
    assert _cell(near, s["pm"]) is None


# ── the items the board had before the rule ───────────────────────────────
# Every trigger this action hangs on is a thing that HAPPENS, so a rule built
# today would have filled only the rows something happened to after today and
# left the ones already linked empty for ever. Building it fills them.

def test_building_the_rule_fills_the_items_already_linked(client, admin_id, member_id):
    s = _stage(client, admin_id, member_id, "bf1", [member_id])
    before = _item(client, s["dst"], admin_id, "קושר לפני הכלל")
    _link(client, before, s["conn"], [s["far"]], admin_id)
    lonely = _item(client, s["dst"], admin_id, "בלי קישור")
    r = _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
              {"a_mirror": s["mir"], "a_person_col": s["pm"]})
    assert r.status_code == 200, r.text
    assert _cell(before, s["pm"]) == [member_id], "the item linked before the rule stayed empty"
    assert _cell(lonely, s["pm"]) is None
    assert r.json()["backfill"]["filled"] == 1, r.json()["backfill"]
    assert "מולאו 1" in r.json()["backfill"]["said"]


def test_the_backfill_tells_nobody_they_were_assigned(client, admin_id, member_id):
    """Three hundred "שויכת למשימה" about work that was theirs yesterday too is
    not a notice anybody wants; the cell is written, the notice is held back."""
    from models import Notification
    s = _stage(client, admin_id, member_id, "bf2", [member_id])
    near = _item(client, s["dst"], admin_id, "קושר לפני הכלל")
    _link(client, near, s["conn"], [s["far"]], admin_id)
    with Session(cityos_main.engine) as db:
        was = db.query(Notification).filter(Notification.user_id == member_id,
                                            Notification.task_id == near).count()
    _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
          {"a_mirror": s["mir"], "a_person_col": s["pm"]})
    assert _cell(near, s["pm"]) == [member_id]
    with Session(cityos_main.engine) as db:
        now = db.query(Notification).filter(Notification.user_id == member_id,
                                            Notification.task_id == near).count()
    assert now == was


def test_a_name_the_board_does_not_have_is_counted_not_guessed(client, admin_id, member_id):
    s = _stage(client, admin_id, member_id, "bf3", "מישהי שאינה בלוח", source_type="text")
    near = _item(client, s["dst"], admin_id, "קושר לפני הכלל")
    _link(client, near, s["conn"], [s["far"]], admin_id)
    r = _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
              {"a_mirror": s["mir"], "a_person_col": s["pm"]})
    assert _cell(near, s["pm"]) is None
    assert r.json()["backfill"]["unmatched"] == 1, r.json()["backfill"]


def test_a_draft_fills_nothing_until_it_is_switched_on(client, admin_id, member_id):
    s = _stage(client, admin_id, member_id, "bf4", [member_id])
    near = _item(client, s["dst"], admin_id, "קושר לפני הכלל")
    _link(client, near, s["conn"], [s["far"]], admin_id)
    r = client.post(f"/api/boards/{s['dst']}/automations?user_id={admin_id}",
                    json={"recipe_id": "link_added_assign_from_mirror", "status": "draft",
                          "config": {"a_mirror": s["mir"], "a_person_col": s["pm"]}})
    assert r.status_code == 200, r.text
    assert _cell(near, s["pm"]) is None, "a draft wrote on the board"
    on = client.patch(f"/api/automations/{r.json()['id']}?user_id={admin_id}",
                      json={"status": "active", "etag": r.json().get("etag")})
    assert on.status_code == 200, on.text
    assert _cell(near, s["pm"]) == [member_id], "publishing the draft did not fill the board"
    assert on.json()["backfill"]["filled"] == 1


def test_no_other_rule_runs_over_the_board_when_it_is_built(client, admin_id, member_id):
    """Only this action: "run every rule over history" would be a flood for a
    notification rule, and nobody asked for that."""
    s = _stage(client, admin_id, member_id, "bf5", [member_id])
    near = _item(client, s["dst"], admin_id, "פריט קיים")
    r = _rule(client, s["dst"], admin_id, "created_assign_person", {"a_person": member_id})
    assert r.status_code == 200, r.text
    assert r.json()["backfill"] is None
    assert _assignees(near) == []


def test_a_mirror_of_any_text_is_read_the_same_way(client, admin_id, member_id):
    """A mirror is TEXT whatever the source column was. A board that keeps the
    responsible person's name in a plain text column is the case this feature
    was asked for, and it must not be a different code path."""
    s = _stage(client, admin_id, member_id, "m3", "בודק חבר", source_type="text")
    assert _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
                 {"a_mirror": s["mir"], "a_person_col": s["pm"]}).status_code == 200
    near = _item(client, s["dst"], admin_id, "פריט יעד")
    _link(client, near, s["conn"], [s["far"]], admin_id)
    assert _cell(near, s["pm"]) == [member_id]


def test_a_name_nobody_on_the_board_answers_to_is_said_out_loud(client, admin_id, member_id):
    """Skipped, and the history names the name. "לא נמצא משתמש" would send
    whoever reads it looking for a bug; the name sends them to the invitation
    list, which is where the problem is."""
    s = _stage(client, admin_id, member_id, "m4", "מישהי שאינה בלוח", source_type="text")
    r = _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
              {"a_mirror": s["mir"], "a_person_col": s["pm"]})
    aid = r.json()["id"]
    near = _item(client, s["dst"], admin_id, "פריט יעד")
    _link(client, near, s["conn"], [s["far"]], admin_id)
    assert _cell(near, s["pm"]) is None
    runs = client.get(f"/api/boards/{s['dst']}/automations/runs"
                      f"?automation_id={aid}&user_id={admin_id}").json()["runs"]
    why = " ".join(str(x) for x in runs)
    assert "מישהי שאינה בלוח" in why, why[:600]


def test_a_name_two_people_on_the_board_share_is_never_guessed(client, admin_id):
    """Putting the wrong דנה on an item is worse than putting nobody on it."""
    twins = []
    for i in (1, 2):
        uid = client.post("/api/users",
                          json={"actor_id": admin_id, "name": "דנה כהן",
                                "email": f"dana.twin{i}@cityos.test",
                                "role": "member"}).json()["id"]
        join_primary_env(client, uid)
        twins.append(uid)
    s = _stage(client, admin_id, twins[0], "m5", "דנה כהן", source_type="text")
    client.post(f"/api/boards/{s['dst']}/members",
                json={"actor_id": admin_id, "user_id": twins[1], "role": "editor"})
    assert _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
                 {"a_mirror": s["mir"], "a_person_col": s["pm"]}).status_code == 200
    near = _item(client, s["dst"], admin_id, "פריט יעד")
    _link(client, near, s["conn"], [s["far"]], admin_id)
    assert _cell(near, s["pm"]) is None, "it picked one of two people with the same name"


# ── בנוסף, או במקום ───────────────────────────────────────────────────────
def test_silence_adds_and_never_takes_anybody_off(client, admin_id, member_id, guinea_id):
    s = _stage(client, admin_id, member_id, "m6", [member_id])
    client.post(f"/api/boards/{s['dst']}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
                 {"a_mirror": s["mir"], "a_person_col": s["pm"]}).status_code == 200
    near = _item(client, s["dst"], admin_id, "פריט יעד", {s["pm"]: [guinea_id]})
    _link(client, near, s["conn"], [s["far"]], admin_id)
    assert _cell(near, s["pm"]) == [guinea_id, member_id], _cell(near, s["pm"])


def test_replace_makes_the_column_a_copy_of_the_mirror(client, admin_id, member_id, guinea_id):
    s = _stage(client, admin_id, member_id, "m7", [member_id])
    client.post(f"/api/boards/{s['dst']}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
                 {"a_mirror": s["mir"], "a_person_col": s["pm"],
                  "a_write": "replace"}).status_code == 200
    near = _item(client, s["dst"], admin_id, "פריט יעד", {s["pm"]: [guinea_id]})
    _link(client, near, s["conn"], [s["far"]], admin_id)
    assert _cell(near, s["pm"]) == [member_id], _cell(near, s["pm"])


def test_an_empty_mirror_never_clears_the_column(client, admin_id, member_id, guinea_id):
    """"במקום" replaces one name with another. It is not a way to empty a
    column the day a link is removed — see PEOPLE_WRITE."""
    s = _stage(client, admin_id, member_id, "m8", [], source_type="people")
    client.post(f"/api/boards/{s['dst']}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
                 {"a_mirror": s["mir"], "a_person_col": s["pm"],
                  "a_write": "replace"}).status_code == 200
    near = _item(client, s["dst"], admin_id, "פריט יעד", {s["pm"]: [guinea_id]})
    _link(client, near, s["conn"], [s["far"]], admin_id)
    assert _cell(near, s["pm"]) == [guinea_id], _cell(near, s["pm"])


# ── it is a real assignment ───────────────────────────────────────────────
def test_the_write_sets_off_the_rules_that_wait_for_an_assignment(client, admin_id, member_id):
    """A people cell gaining somebody is an assignment however the name got
    there — the same promise «עדכן את העמודה» already makes."""
    s = _stage(client, admin_id, member_id, "m9", [member_id])
    assert _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
                 {"a_mirror": s["mir"], "a_person_col": s["pm"]}).status_code == 200
    assert _rule(client, s["dst"], admin_id, "assigned_set_status",
                 {"t_person_col": s["pm"], "a_status": "in_progress"}).status_code == 200
    near = _item(client, s["dst"], admin_id, "פריט יעד")
    _link(client, near, s["conn"], [s["far"]], admin_id)
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == near).first()
        assert cityos_main._task_status_key(t) == "in_progress", cityos_main._task_status_key(t)


# ── a mirror it can no longer read ────────────────────────────────────────
def test_losing_the_mirror_blocks_the_rule_instead_of_silencing_it(client, admin_id, member_id):
    s = _stage(client, admin_id, member_id, "m10", [member_id])
    cfg = {"a_mirror": s["mir"], "a_person_col": s["pm"]}
    assert _rule(client, s["dst"], admin_id,
                 "link_added_assign_from_mirror", cfg).status_code == 200
    keep = [c for c in _cols(client, s["dst"], admin_id) if c["id"] != s["mir"]]
    assert client.patch(f"/api/boards/{s['dst']}",
                        json={"actor_id": admin_id, "columns": keep},
                        headers=AS(admin_id)).status_code == 200
    v = client.post(f"/api/boards/{s['dst']}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "link_added_assign_from_mirror", "config": cfg})
    assert v.status_code == 200, v.text
    assert any("המראה" in b for b in v.json().get("blockers") or []), v.json()


def test_a_board_with_no_mirror_is_not_offered_the_template(client, admin_id):
    """What a template NEEDS is the board's structure, which a person cannot
    answer in the form — so a board with no mirror is told why instead of
    being handed a rule it cannot build."""
    assert "mirror" in recipes.needs_of("link_added_assign_from_mirror")
    assert recipes.NEEDS_HE["mirror"]


# ── the catalog itself ────────────────────────────────────────────────────
def test_the_action_reads_as_one_sentence():
    said = recipes.sentence("link_added_assign_from_mirror")
    assert "{a_mirror}" in said and "{a_write}" in said, said
    assert "·" not in said, f"a blank fell off the end of the sentence: {said}"
    parts = recipes._sentence_parts(recipes.recipe("link_added_assign_from_mirror"))
    assert parts["action_col_kind"] == "people", parts
    assert "{a_person_col}" in parts["action_col"], parts


def test_the_mirror_blank_is_required_and_the_mode_is_not():
    assert recipes.missing_fields("link_added_assign_from_mirror", {}) == ["עמודת המראה"]
    clean, err = recipes.validate("link_added_assign_from_mirror", {"a_mirror": "col_x"})
    assert err is None and clean["a_write"] == recipes.PEOPLE_WRITE_DEFAULT, (clean, err)


def test_the_engine_declares_what_it_writes():
    """A field nobody declared is a field nobody approved."""
    assert "assign_from_mirror" in cityos_main.AUTOMATION_GRANTED_ACTIONS
    for f in cityos_main.AUTOMATION_ACTION_FIELDS["assign_from_mirror"]:
        assert f in cityos_main.AUTOMATION_GRANTED_FIELDS, f
    on_col = cityos_main._action_writes({"key": "assign_from_mirror",
                                         "values": {"person_col": "col_pm"}})
    built_in = cityos_main._action_writes({"key": "assign_from_mirror", "values": {}})
    assert on_col[0] == {"custom_fields_value"} and built_in[0] == {"assignees"}


# ── the browser half ──────────────────────────────────────────────────────
def test_the_builder_offers_mirror_columns_and_nothing_else():
    src = INDEX.read_text(encoding="utf-8")
    assert "if(type==='mirror')" in src, "the blank has no list to offer"
    # …and a mirror stays out of the lists for listening and writing, which is
    # the other half of the same decision
    i = src.index("  _blankCols(fkey,write){")
    assert "'mirror'" in src[i:src.index("\n  },", i)]


def test_the_browser_half():
    r = subprocess.run(["node", str(ROOT / "tests" / "frontend" /
                                    "automation_mirror_to_people_column.mjs")],
                       capture_output=True, text=True)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


# ── the test screen, before anything is written ───────────────────────────
def test_the_test_screen_says_which_names_it_found_and_which_it_did_not(
        client, admin_id, member_id):
    """A preview that reported only "שיוך" would be describing a different
    rule: the whole question somebody tests this one with is which of the
    names in the mirror the board actually has an account for."""
    s = _stage(client, admin_id, member_id, "m11", [member_id])
    aid = _rule(client, s["dst"], admin_id, "link_added_assign_from_mirror",
                {"a_mirror": s["mir"], "a_person_col": s["pm"]}).json()["id"]
    near = _item(client, s["dst"], admin_id, "פריט יעד")
    _link(client, near, s["conn"], [s["far"]], admin_id)
    r = client.post(f"/api/automations/{aid}/test?user_id={admin_id}",
                    json={"task_id": near})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["actions"] if "מראה" in x["what"])
    assert "בודק חבר" in row["to"], row
    assert "מנהל פרויקט" in row["note"] and recipes.PEOPLE_WRITE_HE["add"] in row["note"], row
