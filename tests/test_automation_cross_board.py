"""Group — בין לוחות ותתי־פריטים: reaching off the board, by id and by grant.

A rule that only ever touches its own board is a rule whose blast radius is the
board. The moment it writes somewhere else, three questions it never had to
answer become the whole feature:

  לאן   · to a board named by ID, through a link column or a target board fixed
          in advance. Never by name — two boards called "תשתיות" are two boards
  למי   · to the items linked AT RUN TIME, and when there is more than one, to
          one or to all — chosen by the person who wrote the rule, defaulting to
          one, because "all" is the answer nobody meant to give by accident
  ואם לא · a missing link is a skip or a failure, and which one is a decision
          the author makes rather than one the engine makes for them

And underneath all three: the grant. The target board can be deleted, the link
column can be deleted, the column can stop pointing at that board — and each of
those stops the rule rather than quietly narrowing what it does.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, Board, Task

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title, **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **kw}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _setup(client, admin_id, tag, two_way=True, multiple=True):
    """A source board with a link column pointing at one target board."""
    a, b = _board(client, admin_id, f"מקור {tag}"), _board(client, admin_id, f"יעד {tag}")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": multiple,
                                            "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    return a, b, next(x for x in _cols(client, a) if x["type"] == "connect")


def _rule(client, admin_id, bid, recipe_id, config, **extra):
    return client.post(f"/api/boards/{bid}/automations",
                       json={"actor_id": admin_id, "recipe_id": recipe_id,
                             "config": config, **extra})


def _add(client, admin_id, bid, recipe_id, config, **extra):
    r = _rule(client, admin_id, bid, recipe_id, config, **extra)
    assert r.status_code == 200, r.text
    return r.json()


def _link(client, tid, col_id, ids, uid):
    r = client.patch(f"/api/tasks/{tid}?user_id={uid}",
                     json={"custom_fields": {col_id: ids}}, headers=AS(uid))
    assert r.status_code == 200, r.text
    return r


def _runs(client, bid, admin_id, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}{qs}"
                      ).json()["runs"]


def _title(client, tid, uid):
    return client.get(f"/api/tasks/{tid}", headers=AS(uid)).json()["title"]


def _prio(tid):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        return t.priority.value if hasattr(t.priority, "value") else t.priority


# ── 1. היעד נקבע לפי מזהה, לעולם לא לפי שם ────────────────────────────────

def test_the_target_board_is_an_id_and_never_a_name(client, admin_id):
    """Two boards can be called the same thing. A rule that found its target by
    name would write to whichever one the query happened to return."""
    a, b, c = _setup(client, admin_id, "id1")
    r = _rule(client, admin_id, a, "created_create_and_link",
              {"a_connect": c["id"], "a_board": "יעד id1", "a_text": "חדש"})
    assert r.status_code >= 400, "a board name was accepted as a target"


def test_every_cross_board_field_is_an_id_field(client, admin_id):
    """The audit behind the rule above: no field in the catalog resolves a board
    or a column by its title."""
    import automations as recipes
    for key in ("create_and_link", "create_in_group_and_link", "create_mapped_and_link",
                "link_to_item", "copy_to_linked"):
        for f in recipes.action_fields(key):
            if f["key"] in ("board", "target_group", "item"):
                assert f["type"] in ("board", "target_group", "item"), (key, f)
            if f["key"] == "connect":
                assert f["type"].startswith("connect"), (key, f)


def test_a_board_the_column_does_not_point_at_is_refused(client, admin_id):
    """The link column IS the grant. A target outside it is not a target."""
    a, b, c = _setup(client, admin_id, "id2")
    other = _board(client, admin_id, "לוח שלישי")
    r = _rule(client, admin_id, a, "created_create_and_link",
              {"a_connect": c["id"], "a_board": other, "a_text": "חדש"})
    assert r.status_code >= 400, "a rule reached a board its column never pointed at"


# ── 2. הפריטים המקושרים בפועל בזמן ההפעלה ─────────────────────────────────

def _copy_rule(client, admin_id, a, col, **over):
    cfg = {"a_fields": ["priority"], "a_connect": col["id"]}
    cfg.update(over)
    return _add(client, admin_id, a, "link_added_copy_to_linked", cfg)


def test_the_copy_follows_the_link_as_it_is_now(client, admin_id):
    """Not as the event found it. An item unlinked between the trigger and the
    action is not a linked item, and writing to it anyway is writing to an item
    the rule no longer has any relationship with."""
    a, b, c = _setup(client, admin_id, "live1")
    _copy_rule(client, admin_id, a, c)
    src = _item(client, a, admin_id, "מקור", priority="critical")
    gone = _item(client, b, admin_id, "שנותק")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == src).first()
        # the event names an item that is NOT in the cell — exactly what a wait,
        # or a rule ahead of this one, leaves behind
        cityos_main._run_automations(
            db, t, cityos_main._event("link_added", "item", col=c["id"],
                                      item_ids=[gone]), admin_id)
        db.commit()
    assert _prio(gone) != "critical", "the copy went to an item that is not linked"
    assert [r for r in _runs(client, a, admin_id) if r["outcome"] == "skipped"]


def test_the_copy_reaches_the_item_that_is_linked(client, admin_id):
    a, b, c = _setup(client, admin_id, "live2")
    _copy_rule(client, admin_id, a, c)
    src = _item(client, a, admin_id, "מקור", priority="critical")
    dst = _item(client, b, admin_id, "יעד")
    _link(client, src, c["id"], [dst], admin_id)
    assert _prio(dst) == "critical"


# ── 3. יעד אחד או כולם, וברירת המחדל היא אחד ──────────────────────────────

def test_the_default_is_a_single_target(client, admin_id):
    """«כולם» is the answer nobody means to give by accident."""
    a, b, c = _setup(client, admin_id, "one1")
    _copy_rule(client, admin_id, a, c)
    src = _item(client, a, admin_id, "מקור", priority="critical")
    one = _item(client, b, admin_id, "ראשון")
    two = _item(client, b, admin_id, "שני")
    _link(client, src, c["id"], [one, two], admin_id)
    touched = [x for x in (one, two) if _prio(x) == "critical"]
    assert len(touched) == 1, f"the default reached {len(touched)} items"


def test_all_targets_when_the_author_asked_for_all(client, admin_id):
    a, b, c = _setup(client, admin_id, "all1")
    _copy_rule(client, admin_id, a, c, a_targets="all")
    src = _item(client, a, admin_id, "מקור", priority="critical")
    one = _item(client, b, admin_id, "ראשון")
    two = _item(client, b, admin_id, "שני")
    _link(client, src, c["id"], [one, two], admin_id)
    assert _prio(one) == "critical" and _prio(two) == "critical"


def test_the_choice_is_published_with_its_default(client, admin_id):
    d = client.get(f"/api/automation-capabilities?user_id={admin_id}").json()
    assert d["targets"]["options"] == ["one", "all"]
    assert d["targets"]["default"] == "one"


def test_a_rule_saved_before_the_choice_existed_is_a_single_target(client, admin_id):
    """The old rows have no value in them at all, and the spec says what that
    means: one. Not "whatever the engine used to do"."""
    a, b, c = _setup(client, admin_id, "old1")
    rule = _copy_rule(client, admin_id, a, c)
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == rule["id"]).first()
        cfg = dict(row.config or {})
        cfg.pop("a_targets", None)
        row.config = cfg
        db.commit()
    src = _item(client, a, admin_id, "מקור", priority="critical")
    one = _item(client, b, admin_id, "ראשון")
    two = _item(client, b, admin_id, "שני")
    _link(client, src, c["id"], [one, two], admin_id)
    assert len([x for x in (one, two) if _prio(x) == "critical"]) == 1


# ── 4. אין פריט מקושר: דילוג או כשל, לפי הגדרה ────────────────────────────

def test_no_linked_item_skips_by_default(client, admin_id):
    a, b, c = _setup(client, admin_id, "miss1")
    _copy_rule(client, admin_id, a, c)
    src = _item(client, a, admin_id, "מקור", priority="critical")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == src).first()
        cityos_main._run_automations(
            db, t, cityos_main._event("link_added", "item", col=c["id"], item_ids=[]),
            admin_id)
        db.commit()
    runs = _runs(client, a, admin_id)
    assert runs and runs[0]["outcome"] == "skipped", runs


def test_no_linked_item_fails_when_the_author_said_so(client, admin_id):
    """Some rules are the whole point of the link. A silent skip there is a
    board that looks automated and is not."""
    a, b, c = _setup(client, admin_id, "miss2")
    _copy_rule(client, admin_id, a, c, a_on_missing="fail")
    src = _item(client, a, admin_id, "מקור", priority="critical")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == src).first()
        cityos_main._run_automations(
            db, t, cityos_main._event("link_added", "item", col=c["id"], item_ids=[]),
            admin_id)
        db.commit()
    runs = _runs(client, a, admin_id)
    assert runs and runs[0]["outcome"] == "failed", runs
    assert "מקושר" in (runs[0]["reason"] or ""), runs[0]


def test_the_missing_choice_is_published_too(client, admin_id):
    d = client.get(f"/api/automation-capabilities?user_id={admin_id}").json()
    assert d["on_missing"]["options"] == ["skip", "fail"]
    assert d["on_missing"]["default"] == "skip"


# ── 5. מחיקת לוח יעד, עמודת קישור או שדה יעד משהה ─────────────────────────

def _status_of(rule_id):
    with Session(cityos_main.engine) as db:
        return db.query(Automation).filter(Automation.id == rule_id).first().status


def test_deleting_the_target_board_suspends_the_rule(client, admin_id):
    a, b, c = _setup(client, admin_id, "sus1")
    rule = _add(client, admin_id, a, "created_create_and_link",
                {"a_connect": c["id"], "a_board": b, "a_text": "חדש"})
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    _item(client, a, admin_id, "מפעיל")
    assert _status_of(rule["id"]) == "paused_error", _status_of(rule["id"])


def test_deleting_the_link_column_suspends_the_rule(client, admin_id):
    a, b, c = _setup(client, admin_id, "sus2")
    rule = _add(client, admin_id, a, "created_create_and_link",
                {"a_connect": c["id"], "a_board": b, "a_text": "חדש"})
    cols = [x for x in _cols(client, a) if x["id"] != c["id"]]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    _item(client, a, admin_id, "מפעיל")
    assert _status_of(rule["id"]) == "paused_error", _status_of(rule["id"])


def test_deleting_the_link_column_suspends_a_copy_rule_too(client, admin_id):
    """The copy rule names its column as well, and a column that is gone is the
    same gone for both."""
    a, b, c = _setup(client, admin_id, "sus3")
    rule = _copy_rule(client, admin_id, a, c)
    cols = [x for x in _cols(client, a) if x["id"] != c["id"]]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    src = _item(client, a, admin_id, "מקור")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == src).first()
        cityos_main._run_automations(
            db, t, cityos_main._event("link_added", "item", col=c["id"], item_ids=[1]),
            admin_id)
        db.commit()
    assert _status_of(rule["id"]) == "paused_error", _status_of(rule["id"])


def test_deleting_a_mapped_target_field_suspends_the_rule(client, admin_id):
    """«שדה יעד» — the far half of a field mapping. Mapping onto a column that
    is gone is not a smaller copy, it is a rule that cannot do what it says."""
    a, b, c = _setup(client, admin_id, "sus4")
    bcols = _cols(client, b) + [{"id": "col_tgt", "type": "text", "title": "הערה"}]
    client.patch(f"/api/boards/{b}", json={"actor_id": admin_id, "columns": bcols})
    acols = _cols(client, a) + [{"id": "col_src", "type": "text", "title": "אזור"}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": acols})
    grp = client.get(f"/api/boards/{b}").json()["groups"][0]["id"]
    rule = _add(client, admin_id, a, "created_set_status",
                {"a_status": "in_progress",
                 "actions": [{"key": "create_mapped_and_link",
                              "values": {"connect": c["id"], "board": b,
                                         "target_group": grp, "text": "ממופה",
                                         "map": [{"from": "col_src", "to": "col_tgt"}]}}]})
    _item(client, a, admin_id, "לפני")
    assert _status_of(rule["id"]) == "active", "the rule was broken before the test began"
    client.patch(f"/api/boards/{b}", json={"actor_id": admin_id,
                                           "columns": [x for x in bcols
                                                       if x["id"] != "col_tgt"]})
    _item(client, a, admin_id, "מפעיל")
    assert _status_of(rule["id"]) == "paused_error", _status_of(rule["id"])


# ── 6. מענק הרשאה פעיל ללוח ולשדות היעד ───────────────────────────────────

def test_a_column_that_stops_pointing_at_the_board_suspends_the_rule(client, admin_id):
    """The grant is live, not a note from when the rule was written."""
    a, b, c = _setup(client, admin_id, "grant1")
    rule = _add(client, admin_id, a, "created_create_and_link",
                {"a_connect": c["id"], "a_board": b, "a_text": "חדש"})
    other = _board(client, admin_id, "יעד אחר grant1")
    cols = [dict(x, connect={**x["connect"], "board_ids": [other]})
            if x["id"] == c["id"] else x for x in _cols(client, a)]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    _item(client, a, admin_id, "מפעיל")
    assert _status_of(rule["id"]) == "paused_error", _status_of(rule["id"])


def test_an_author_without_rights_on_the_target_cannot_write_the_rule(client, admin_id, guinea_id):
    """"המגדיר אוטומציה בין לוחות חייב להיות מנהל בלוח המקור ובעל הרשאת עריכה
    בלוח היעד" — checked where the rule is written, by the person writing it."""
    a, b, c = _setup(client, admin_id, "grant2")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    r = _rule(client, guinea_id, a, "created_create_and_link",
              {"a_connect": c["id"], "a_board": b, "a_text": "חדש"})
    assert r.status_code == 403, r.text


def test_the_copy_never_crosses_an_organisation(client, admin_id):
    """Whatever a column was configured for once, an item on another
    organisation's board is not something this engine writes to."""
    a, b, c = _setup(client, admin_id, "org1")
    src = _item(client, a, admin_id, "מקור", priority="critical")
    dst = _item(client, b, admin_id, "יעד")
    _link(client, src, c["id"], [dst], admin_id)
    _copy_rule(client, admin_id, a, c, a_targets="all")
    with Session(cityos_main.engine) as db:
        tb = db.query(Board).filter(Board.id == b).first()
        tb.organization_id = (tb.organization_id or 1) + 999
        db.commit()
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == src).first()
        t.priority = "emergency"
        cityos_main._run_automations(
            db, t, cityos_main._event("link_added", "item", col=c["id"], item_ids=[dst]),
            admin_id)
        db.commit()
    assert _prio(dst) != "emergency", "a rule wrote onto another organisation's board"


# ── תתי־פריטים ─────────────────────────────────────────────────────────────

def test_a_subitem_being_created_reaches_the_parents_rule_by_id(client, admin_id):
    a = _board(client, admin_id, "לוח תתי-פריטים")
    _add(client, admin_id, a, "subitem_created_set_status", {"a_status": "in_progress"})
    parent = _item(client, a, admin_id, "אב")
    sub = _item(client, a, admin_id, "תת", parent_id=parent)
    runs = [r for r in _runs(client, a, admin_id) if r["outcome"] == "ran"]
    assert runs, _runs(client, a, admin_id)
    assert runs[0]["task_id"] == parent, "the rule acted on the sub-item, not the parent"
    with Session(cityos_main.engine) as db:
        from models import AutomationRun
        row = db.query(AutomationRun).filter(AutomationRun.id == runs[0]["id"]).first()
        assert (row.event or {}).get("subitem_id") == sub, \
            "the event did not name which sub-item it was about"


def test_a_subitem_finishing_acts_on_the_parent(client, admin_id):
    a = _board(client, admin_id, "לוח תת הושלם")
    _add(client, admin_id, a, "subitem_done_set_priority", {"a_priority": "critical"})
    parent = _item(client, a, admin_id, "אב")
    sub = _item(client, a, admin_id, "תת", parent_id=parent)
    client.patch(f"/api/tasks/{sub}", json={"status": "done", "user_id": admin_id})
    assert _prio(parent) == "critical"
    assert _prio(sub) != "critical", "the rule wrote onto the sub-item as well"
