"""Group — ספריית התבניות: the catalog as something to look through.

  · The nine templates the specification recommends, under the names it gives
    them, at the top of the list.
  · Search, and filters for the six things a person has in mind: a status, a
    date, who it is assigned to, a sub-item, a link, a notification.
  · A template that does not fit the board is shown as unavailable, saying what
    the board is missing — not quietly left out of the list.
  · Choosing one makes a DRAFT, which cannot run until its blanks are filled.
  · A system template is versioned, and a rule already built from it does not
    move when the template does.
"""
from sqlalchemy.orm import Session
import automations as recipes
import main as cityos_main
from models import Automation, Comment, Group, Task


def _board(client, admin_id, name="לוח תבניות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _member(client, admin_id, bid, uid, role="editor"):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    assert r.status_code == 200, r.text


def _item(client, bid, admin_id, title="פריט", **extra):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **extra}).json()["id"]


def _lib(client, bid, uid, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    r = client.get(f"/api/boards/{bid}/automations/templates?user_id={uid}{qs}")
    assert r.status_code == 200, r.text
    return r.json()


def _add(client, bid, admin_id, recipe_id, config, **extra):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config, **extra})


def _connect_board(client, admin_id, name, targets, two_way=False):
    bid = _board(client, admin_id, name)
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    cols.append({"id": "col_link", "type": "connect", "title": "קישור",
                 "connect": {"board_ids": targets, "multi": True, "two_way": two_way}})
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    assert r.status_code == 200, r.text
    return bid


# ── the nine ────────────────────────────────────────────────────────────────

def test_the_nine_recommended_templates_are_all_there(client, admin_id):
    bid = _board(client, admin_id)
    d = _lib(client, bid, admin_id)
    rows = {t["id"]: t for t in d["templates"]}
    for rid, title in recipes.MVP_TEMPLATES:
        assert rid in rows, f"{title} has no recipe"
        assert rows[rid]["recommended"] is True
        assert rows[rid]["title"] == title
    assert [t["id"] for t in d["templates"][:9]] == [r for r, _ in recipes.MVP_TEMPLATES], \
        "the recommended nine are not at the top, in order"


def test_every_recommended_template_declares_what_it_asks_for(client, admin_id):
    """A template is a sentence with blanks. Every blank in it is declared —
    as a field, or as a condition that still needs a value — so the draft the
    library makes can say what is left to fill."""
    for rid, title in recipes.MVP_TEMPLATES:
        r = recipes.recipe(rid)
        s = recipes.sentence(rid)
        assert s, rid
        blanks = {k.strip("{}") for k in __import__("re").findall(r"\{[a-z_]+\}", s)}
        assert blanks <= {f["key"] for f in r["fields"]}, (rid, blanks)
        asks = len(r["fields"]) + sum(1 for c in recipes.recipe_conditions(rid) if c["type"])
        assert asks or rid in ("subitem_done_notify_assignees",), \
            f"{title} asks for nothing — nothing to complete before activation"


def test_a_templates_own_condition_is_filled_before_it_is_stored_at_all(client, admin_id):
    """Template 3's blank is in its CONDITION — "הסטטוס אינו …" — and that one
    is NOT a blank a draft may hold.

    A field left empty makes the rule incomplete and it cannot be switched on.
    A condition left empty would make it WIDER: "רק אם הסטטוס אינו …" with no
    status is not a narrower rule, it is the rule without the condition, and a
    draft holding one would quietly become that the moment somebody activated
    it. So it is refused on the way in, naming the condition — which is what
    the builder fills in before it saves. See validate_conditions.
    """
    bid = _board(client, admin_id, "לוח תנאי תבנית")
    half = _add(client, bid, admin_id, "cond_due_open_notify_assignees",
                {"conditions": [{"kind": "status_is_not"}, {"kind": "has_assignee"}]},
                status="draft")
    assert half.status_code == 400, half.text
    assert "הסטטוס אינו" in half.json()["detail"], half.text
    whole = _add(client, bid, admin_id, "cond_due_open_notify_assignees",
                 {"conditions": [{"kind": "status_is_not", "value": "done"},
                                 {"kind": "has_assignee"}]})
    assert whole.status_code == 200, whole.text
    assert whole.json()["conditions"][0]["value"] == "done"


# ── search and the six filters ──────────────────────────────────────────────

def test_the_six_filters_are_the_six_in_the_spec(client, admin_id):
    bid = _board(client, admin_id)
    d = _lib(client, bid, admin_id)
    assert [t["key"] for t in d["tags"]] == ["status", "date", "assign", "subitem",
                                             "link", "notify"]
    assert all(t["label"] for t in d["tags"])


def test_filtering_by_a_tag_leaves_only_templates_about_it(client, admin_id):
    bid = _board(client, admin_id)
    for key in ("status", "date", "assign", "subitem", "link", "notify"):
        rows = _lib(client, bid, admin_id, tags=key)["templates"]
        assert rows, f"no template is about {key}"
        assert all(key in t["tags"] for t in rows), key


def test_two_filters_narrow_rather_than_widen(client, admin_id):
    bid = _board(client, admin_id)
    both = _lib(client, bid, admin_id, tags="link,status")["templates"]
    one = _lib(client, bid, admin_id, tags="link")["templates"]
    assert both and len(both) <= len(one)
    assert all({"link", "status"} <= set(t["tags"]) for t in both)


def test_search_matches_the_wording_a_person_would_use(client, admin_id):
    bid = _board(client, admin_id)
    rows = _lib(client, bid, admin_id, q="תת־פריט")["templates"]
    assert rows and all("תת" in (t["title"] + t["sentence"]) or "subitem" in t["tags"]
                        for t in rows)
    assert _lib(client, bid, admin_id, q="קבוצ")["templates"]
    assert _lib(client, bid, admin_id, q="שאיןכזהדבר")["templates"] == []


def test_only_recommended_narrows_to_the_nine(client, admin_id):
    bid = _board(client, admin_id)
    rows = _lib(client, bid, admin_id, only="recommended")["templates"]
    assert len(rows) == len(recipes.MVP_TEMPLATES)


# ── compatibility with the board ────────────────────────────────────────────

def test_a_template_that_needs_a_connect_column_is_unavailable_without_one(client, admin_id):
    bare = _board(client, admin_id, "לוח בלי קישור")
    rows = {t["id"]: t for t in _lib(client, bare, admin_id)["templates"]}
    t = rows["created_create_and_link"]
    assert t["available"] is False
    assert t["missing"] == ["עמודת קישור בלוח"], t["missing"]
    # and it is still listed, not quietly dropped
    assert t["id"] in rows and _lib(client, bare, admin_id)["unavailable"] >= 1


def test_the_same_template_is_available_once_the_board_has_one(client, admin_id):
    far = _board(client, admin_id, "לוח יעד לתבנית")
    near = _connect_board(client, admin_id, "לוח עם קישור", [far])
    rows = {t["id"]: t for t in _lib(client, near, admin_id)["templates"]}
    assert rows["created_create_and_link"]["available"] is True
    assert rows["created_create_and_link"]["missing"] == []


def test_a_two_way_column_is_asked_for_where_it_is_really_needed(client, admin_id):
    far = _board(client, admin_id, "יעד דו כיווני")
    one_way = _connect_board(client, admin_id, "קישור חד כיווני", [far])
    rows = {t["id"]: t for t in _lib(client, one_way, admin_id)["templates"]}
    t = rows["linked_status_set_status"]
    assert t["available"] is False and t["missing"] == ["עמודת קישור דו־כיוונית בלוח"]

    two_way = _connect_board(client, admin_id, "קישור דו כיווני", [far], two_way=True)
    rows = {t["id"]: t for t in _lib(client, two_way, admin_id)["templates"]}
    assert rows["linked_status_set_status"]["available"] is True


def test_a_board_nobody_is_on_cannot_use_a_template_that_names_a_person(client, admin_id):
    bid = _board(client, admin_id, "לוח בלי אנשים")
    with Session(cityos_main.engine) as db:
        db.query(cityos_main.BoardMember).filter(
            cityos_main.BoardMember.board_id == bid).delete()
        db.commit()
    rows = {t["id"]: t for t in _lib(client, bid, admin_id)["templates"]}
    assert rows["created_assign_person"]["available"] is False
    assert rows["created_assign_person"]["missing"] == ["לפחות משתמש אחד מוזמן ללוח"]


def test_the_library_follows_the_viewing_permission(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח תבניות פרטי")
    _member(client, admin_id, bid, member_id, "viewer")
    assert client.get(f"/api/boards/{bid}/automations/templates?user_id={member_id}"
                      ).status_code == 403
    assert client.get(f"/api/boards/{10 ** 7}/automations/templates?user_id={admin_id}"
                      ).status_code == 404


# ── choosing one makes a draft that has to be completed ─────────────────────

def test_choosing_a_template_makes_a_draft_that_cannot_run_until_it_is_filled(client,
                                                                              admin_id):
    bid = _board(client, admin_id, "לוח טיוטה מתבנית")
    r = _add(client, bid, admin_id, "created_assign_person", {}, status="draft")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["status"] == "draft" and a["missing_fields"] == ["אחראי"]
    on = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                      json={"status": "active"})
    assert on.status_code == 400 and "חסרים שדות חובה" in on.json()["detail"]
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"config": {"a_person": admin_id}})
    assert client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                        json={"status": "active"}).status_code == 200


def test_a_template_cannot_be_created_active_half_filled(client, admin_id):
    bid = _board(client, admin_id, "לוח חצי")
    assert _add(client, bid, admin_id, "created_assign_person", {}).status_code == 400


# ── versions ────────────────────────────────────────────────────────────────

def test_a_rule_records_which_version_of_the_template_it_was_built_from(client, admin_id):
    bid = _board(client, admin_id, "לוח גרסת תבנית")
    a = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()
    assert a["template_version"] == 1 and a["template_current"] == 1


def test_moving_a_template_on_does_not_move_the_rules_made_from_it(client, admin_id,
                                                                    monkeypatch):
    bid = _board(client, admin_id, "לוח גרסה חדשה")
    before = _add(client, bid, admin_id, "created_set_priority",
                  {"a_priority": "high"}).json()
    monkeypatch.setitem(recipes.TEMPLATE_VERSIONS, "created_set_priority", 2)

    rows = {t["id"]: t for t in _lib(client, bid, admin_id)["templates"]}
    assert rows["created_set_priority"]["version"] == 2, "the library shows the old version"

    after = _add(client, bid, admin_id, "created_set_priority",
                 {"a_priority": "low"}).json()
    assert after["template_version"] == 2

    got = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()["automations"]
    old = next(x for x in got if x["id"] == before["id"])
    assert old["template_version"] == 1, "an existing rule was moved to the new version"
    assert old["template_current"] == 2                 # and it can be told that it is behind
    assert old["config"] == {"a_priority": "high"}      # with its own answers untouched
    assert old["status"] == "active" and old["is_active"] is True


def test_a_copy_answers_the_same_version_as_the_rule_it_came_from(client, admin_id,
                                                                   monkeypatch):
    bid = _board(client, admin_id, "לוח עותק גרסה")
    a = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()
    monkeypatch.setitem(recipes.TEMPLATE_VERSIONS, "created_set_priority", 3)
    c = client.post(f"/api/automations/{a['id']}/duplicate?user_id={admin_id}").json()
    assert c["template_version"] == 1, c["template_version"]


# ── the four templates that had no recipe, doing what they say ─────────────

def test_a_subitem_finishing_updates_its_parent(client, admin_id):
    """"כאשר תת־פריט הושלם, עדכן שדה בפריט האב". The rule acts on the PARENT,
    which is why every action in the catalog is available to it."""
    bid = _board(client, admin_id, "לוח תתי פריטים")
    _add(client, bid, admin_id, "subitem_done_set_status", {"a_status": "done"})
    parent = _item(client, bid, admin_id, "פריט אב")
    sub = client.post("/api/tasks", json={"board_id": bid, "title": "תת־פריט",
                                          "parent_id": parent, "user_id": admin_id}
                      ).json()["id"]
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == parent).first()) != "done"
    client.patch(f"/api/tasks/{sub}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == parent).first()) == "done"


def test_a_subitem_that_is_not_finished_leaves_the_parent_alone(client, admin_id):
    bid = _board(client, admin_id, "לוח תת פריט בעבודה")
    _add(client, bid, admin_id, "subitem_done_set_status", {"a_status": "done"})
    parent = _item(client, bid, admin_id, "אב")
    sub = client.post("/api/tasks", json={"board_id": bid, "title": "תת", "parent_id": parent,
                                          "user_id": admin_id}).json()["id"]
    client.patch(f"/api/tasks/{sub}", json={"status": "in_progress", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == parent).first()) != "done"


def test_an_ordinary_item_finishing_is_not_a_subitem_finishing(client, admin_id):
    """A top-level item has no parent, so the trigger has nobody to tell."""
    bid = _board(client, admin_id, "לוח בלי אב")
    _add(client, bid, admin_id, "subitem_done_set_priority", {"a_priority": "critical"})
    one, two = _item(client, bid, admin_id, "א"), _item(client, bid, admin_id, "ב")
    client.patch(f"/api/tasks/{one}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        assert cityos_main._task_priority_key(
            db.query(Task).filter(Task.id == two).first()) != "critical"


def test_an_assignment_writes_an_update_into_the_conversation(client, admin_id, guinea_id):
    """"כאשר אחראי משתנה, הוסף עדכון לשיחת הפריט"."""
    bid = _board(client, admin_id, "לוח עדכונים")
    _member(client, admin_id, bid, guinea_id, "editor")
    _add(client, bid, admin_id, "assigned_post_update", {"a_text": "האחריות עודכנה"})
    tid = _item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/assignees",
                json={"actor_id": admin_id, "user_id": guinea_id})
    with Session(cityos_main.engine) as db:
        rows = db.query(Comment).filter(Comment.task_id == tid).all()
        assert len(rows) == 1 and rows[0].content == "האחריות עודכנה"
        # written by the engine's own account, and pulling nobody into a thread
        assert rows[0].user_id == cityos_main._automation_identity(db)
        assert (rows[0].mentions or []) == []


def test_linking_an_item_copies_the_fields_that_were_named(client, admin_id):
    """"כאשר פריט מקושר, העתק ערך מוגדר לפריט המקושר"."""
    far = _board(client, admin_id, "לוח יעד להעתקה")
    near = _connect_board(client, admin_id, "לוח מקור להעתקה", [far])
    _add(client, near, admin_id, "link_added_copy_to_linked",
         {"a_fields": ["status", "priority"]})
    src = _item(client, near, admin_id, "מקור", status="done", priority="critical")
    dst = _item(client, far, admin_id, "יעד")
    r = client.patch(f"/api/tasks/{src}",
                     json={"user_id": admin_id, "custom_fields": {"col_link": [dst]}})
    assert r.status_code == 200, r.text
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == dst).first()
        assert cityos_main._st_of(t) == "done"
        assert cityos_main._task_priority_key(t) == "critical"


def test_only_the_named_fields_travel(client, admin_id):
    far = _board(client, admin_id, "יעד שדות")
    near = _connect_board(client, admin_id, "מקור שדות", [far])
    _add(client, near, admin_id, "link_added_copy_to_linked", {"a_fields": ["priority"]})
    src = _item(client, near, admin_id, "מקור", status="done", priority="critical")
    dst = _item(client, far, admin_id, "יעד")
    client.patch(f"/api/tasks/{src}",
                 json={"user_id": admin_id, "custom_fields": {"col_link": [dst]}})
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == dst).first()
        assert cityos_main._task_priority_key(t) == "critical"
        assert cityos_main._st_of(t) != "done", "a field nobody named was copied"


def test_a_status_change_creates_the_item_in_the_group_that_was_chosen(client, admin_id):
    """"כאשר סטטוס בלוח המקור משתנה ל־[ערך], צור פריט חדש בקבוצה [קבוצה] בלוח
    [לוח יעד], העתק אליו את השדות שהוגדרו וקשר אותו לפריט המקור"."""
    far = _board(client, admin_id, "לוח יעד מלא")
    near = _connect_board(client, admin_id, "לוח מקור מלא", [far])
    grp = client.post("/api/groups", json={"board_id": far, "name": "נכנסים",
                                           "actor_id": admin_id}).json()["id"]
    _add(client, near, admin_id, "status_create_in_group_and_link",
         {"t_status": "done", "a_connect": "col_link", "a_board": far,
          "a_target_group": grp, "a_text": "המשך טיפול",
          "a_fields": ["priority", "due"]})
    src = _item(client, near, admin_id, "מקור", priority="critical",
                due_date="2026-12-01T00:00:00")
    client.patch(f"/api/tasks/{src}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == far,
                                     Task.title == "המשך טיפול").first()
        assert made is not None, "no item was created on the target board"
        assert made.group_id == grp, "it was not put in the group that was chosen"
        assert cityos_main._task_priority_key(made) == "critical"
        assert made.due_date is not None
        # and it is linked back to the item that produced it
        assert dst_linked(db, src, made.id)


def dst_linked(db, src_id, made_id):
    src = db.query(Task).filter(Task.id == src_id).first()
    return made_id in ((src.custom_fields or {}).get("col_link") or []) \
        or bool(cityos_main._linked_ids(db, src_id, "col_link"))


def test_a_group_that_was_deleted_stops_the_rule_rather_than_guessing(client, admin_id):
    far = _board(client, admin_id, "יעד בלי קבוצה")
    near = _connect_board(client, admin_id, "מקור בלי קבוצה", [far])
    grp = client.post("/api/groups", json={"board_id": far, "name": "זמנית",
                                           "actor_id": admin_id}).json()["id"]
    a = _add(client, near, admin_id, "status_create_in_group_and_link",
             {"t_status": "done", "a_connect": "col_link", "a_board": far,
              "a_target_group": grp, "a_text": "פריט", "a_fields": ["priority"]}).json()
    client.delete(f"/api/groups/{grp}?actor_id={admin_id}")
    src = _item(client, near, admin_id, "מקור")
    client.patch(f"/api/tasks/{src}", json={"status": "done", "user_id": admin_id})
    runs = client.get(f"/api/boards/{near}/automations/runs?user_id={admin_id}"
                      ).json()["runs"]
    assert runs and runs[0]["outcome"] == "skipped", runs[:1]
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.board_id == far,
                                     Task.title == "פריט").count() == 0


def test_a_board_with_no_column_to_listen_to_says_so(client, admin_id):
    """"ערך שדה השתנה" needs a column that is not a mirror, a connect or a
    formula — the three a rule may not be hung on."""
    bare = _board(client, admin_id, "לוח בלי עמודות")
    with Session(cityos_main.engine) as db:
        b = db.query(cityos_main.Board).filter(cityos_main.Board.id == bare).first()
        b.settings = {**(b.settings or {}), "columns": []}
        db.commit()
    rows = {t["id"]: t for t in _lib(client, bare, admin_id)["templates"]}
    t = rows["column_changed_notify_assignees"]
    assert t["available"] is False
    assert t["missing"] == ["עמודה מותאמת בלוח (לא מראה ולא קישור)"], t["missing"]


def test_a_board_with_an_ordinary_column_can_use_it(client, admin_id):
    bid = _board(client, admin_id, "לוח עם עמודה")
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    cols.append({"id": "col_txt", "type": "text", "title": "הערה"})
    client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    rows = {t["id"]: t for t in _lib(client, bid, admin_id)["templates"]}
    assert rows["column_changed_notify_assignees"]["available"] is True


def test_a_mirror_alone_is_not_a_column_to_listen_to(client, admin_id):
    far = _board(client, admin_id, "יעד זמינות")
    bid = _board(client, admin_id, "לוח מראה בלבד")
    with Session(cityos_main.engine) as db:
        b = db.query(cityos_main.Board).filter(cityos_main.Board.id == bid).first()
        b.settings = {**(b.settings or {}), "columns": [
            {"id": "col_link", "type": "connect", "title": "קישור",
             "connect": {"board_ids": [far], "multi": True}},
            {"id": "col_mir", "type": "mirror", "title": "מראה",
             "mirror_of": {"connect": "col_link", "field": "status"}}]}
        db.commit()
    rows = {t["id"]: t for t in _lib(client, bid, admin_id)["templates"]}
    assert rows["column_changed_notify_assignees"]["available"] is False
