"""Group — יצירת פריט בלוח יעד בעקבות שינוי סטטוס.

The one cross-board scenario the spec writes out end to end, and the reason it
gets a section of its own is that it is the first automation that CREATES. Every
other action edits something that already exists, and an edit applied twice is
the same edit. A creation applied twice is two items, on somebody else's board,
and nobody is watching that board for duplicates.

So four things hold it together:

  פעם אחת   · at most one target item per source item per rule, ever. A repeat
              event, a retry, a status that left and came back — all the same
              answer: "דולגה - פריט יעד כבר קיים"
  במעבר     · on the change to the value, not on every save of the item
  אטומית    · the item and its mapped fields are one act. A value the target
              field cannot hold takes the whole creation back with it
  ומתועדת   · the log keeps the source item, the status change, the target board
              and group, the mapping and the id of what was made — a creation
              nobody can point at afterwards is a creation nobody can undo
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AutomationRun, Board, Task

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title, **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **kw}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _col(client, bid, admin_id, **spec):
    cols = _cols(client, bid)
    col = {"id": spec.pop("id", "col_" + spec["type"][:4] + str(len(cols))), **spec}
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols + [col]})
    return col


def _setup(client, admin_id, tag, two_way=True):
    a, b = _board(client, admin_id, f"מקור {tag}"), _board(client, admin_id, f"יעד {tag}")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True,
                                            "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    col = next(x for x in _cols(client, a) if x["type"] == "connect")
    grp = client.get(f"/api/boards/{b}").json()["groups"][0]["id"]
    return a, b, col, grp


def _rule(client, admin_id, a, b, col, grp, **over):
    cfg = {"t_status": "done", "a_connect": col["id"], "a_board": b,
           "a_target_group": grp, "a_text": "משימת יעד", "a_fields": ["priority"]}
    cfg.update(over)
    r = client.post(f"/api/boards/{a}/automations",
                    json={"actor_id": admin_id,
                          "recipe_id": "status_create_in_group_and_link", "config": cfg})
    assert r.status_code == 200, r.text
    return r.json()


def _made(bid):
    """Everything on the target board that a rule put there."""
    with Session(cityos_main.engine) as db:
        return [t.id for t in db.query(Task).filter(Task.board_id == bid,
                                                    Task.title == "משימת יעד").all()]


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}"
                      ).json()["runs"]


def _status(client, tid, admin_id, value):
    r = client.patch(f"/api/tasks/{tid}", json={"status": value, "user_id": admin_id})
    assert r.status_code == 200, r.text


# ── זרימה תקינה ────────────────────────────────────────────────────────────

def test_a_status_change_creates_one_item_on_the_target_board(client, admin_id):
    a, b, col, grp = _setup(client, admin_id, "ok1")
    _rule(client, admin_id, a, b, col, grp)
    src = _item(client, a, admin_id, "מקור", priority="critical")
    _status(client, src, admin_id, "done")
    made = _made(b)
    assert len(made) == 1, made
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == made[0]).first()
        assert t.group_id == grp, "the item was not filed in the group the rule names"
        prio = t.priority.value if hasattr(t.priority, "value") else t.priority
        assert prio == "critical", "the mapped field did not travel"


def test_the_two_items_point_at_each_other(client, admin_id):
    """«מזהה פריט היעד יישמר בפריט המקור ומזהה פריט המקור יישמר בפריט היעד»."""
    a, b, col, grp = _setup(client, admin_id, "link1")
    _rule(client, admin_id, a, b, col, grp)
    src = _item(client, a, admin_id, "מקור")
    _status(client, src, admin_id, "done")
    target = _made(b)[0]
    with Session(cityos_main.engine) as db:
        assert target in cityos_main._linked_ids(db, src, col["id"]), \
            "the source does not hold the target's id"
        mirror = col["connect"]["mirror"][str(b)]
        assert src in cityos_main._linked_ids(db, target, mirror), \
            "the target does not hold the source's id"


# ── רק במעבר, לא בכל שמירה ────────────────────────────────────────────────

def test_saving_the_item_again_in_the_same_status_creates_nothing(client, admin_id):
    a, b, col, grp = _setup(client, admin_id, "trans1")
    _rule(client, admin_id, a, b, col, grp)
    src = _item(client, a, admin_id, "מקור")
    _status(client, src, admin_id, "done")
    client.patch(f"/api/tasks/{src}", json={"title": "מקור בשם אחר", "user_id": admin_id})
    client.patch(f"/api/tasks/{src}", json={"status": "done", "user_id": admin_id})
    assert len(_made(b)) == 1, "a save that changed nothing created a second item"


def test_another_status_does_not_set_it_off(client, admin_id):
    a, b, col, grp = _setup(client, admin_id, "trans2")
    _rule(client, admin_id, a, b, col, grp)
    src = _item(client, a, admin_id, "מקור")
    _status(client, src, admin_id, "in_progress")
    assert _made(b) == []


# ── פעם אחת, ולא יותר ─────────────────────────────────────────────────────

def test_leaving_the_status_and_coming_back_creates_nothing(client, admin_id):
    """The requirement that is easiest to get wrong and worst to get wrong:
    a board where the status moves back and forth is a board that quietly
    grows a hundred copies on somebody else's board."""
    a, b, col, grp = _setup(client, admin_id, "once1")
    _rule(client, admin_id, a, b, col, grp)
    src = _item(client, a, admin_id, "מקור")
    for _ in range(3):
        _status(client, src, admin_id, "done")
        _status(client, src, admin_id, "todo")
    assert len(_made(b)) == 1, f"{len(_made(b))} items for one source item"


def test_the_second_firing_says_why_it_did_nothing(client, admin_id):
    a, b, col, grp = _setup(client, admin_id, "once2")
    _rule(client, admin_id, a, b, col, grp)
    src = _item(client, a, admin_id, "מקור")
    _status(client, src, admin_id, "done")
    _status(client, src, admin_id, "todo")
    _status(client, src, admin_id, "done")
    runs = _runs(client, a, admin_id)
    skipped = [r for r in runs if r["outcome"] == "skipped"]
    assert skipped, runs
    assert "פריט יעד כבר קיים" in (skipped[0]["reason"] or ""), skipped[0]


def test_a_retry_does_not_duplicate_either(client, admin_id):
    a, b, col, grp = _setup(client, admin_id, "once3")
    _rule(client, admin_id, a, b, col, grp)
    src = _item(client, a, admin_id, "מקור")
    _status(client, src, admin_id, "done")
    run = [r for r in _runs(client, a, admin_id) if r["outcome"] == "ran"][0]
    client.post(f"/api/automation-runs/{run['id']}/retry?user_id={admin_id}")
    assert len(_made(b)) == 1, "a retry made a second item"


def test_a_second_source_item_gets_its_own_target(client, admin_id):
    """The cap is per source item, not per rule. A rule that fired once and
    then never again would be a rule nobody could use."""
    a, b, col, grp = _setup(client, admin_id, "once4")
    _rule(client, admin_id, a, b, col, grp)
    for name in ("ראשון", "שני"):
        _status(client, _item(client, a, admin_id, name), admin_id, "done")
    assert len(_made(b)) == 2, _made(b)


def test_two_rules_on_one_item_are_two_targets(client, admin_id):
    """And it is per rule as well: two different rules are two different
    intentions, and neither is the other's duplicate."""
    a, b, col, grp = _setup(client, admin_id, "once5")
    _rule(client, admin_id, a, b, col, grp)
    _rule(client, admin_id, a, b, col, grp, a_text="משימת יעד")
    src = _item(client, a, admin_id, "מקור")
    _status(client, src, admin_id, "done")
    assert len(_made(b)) == 2, _made(b)


# ── אטומיות ────────────────────────────────────────────────────────────────

def test_a_value_the_target_field_cannot_hold_creates_nothing(client, admin_id):
    """«אם שדה חובה אינו ניתן למילוי, הפריט לא ייווצר». The item and its fields
    are one act: half an item, with the log saying it worked, is the thing
    worth not having.

    Two dropdowns are a mapping the save-time check passes — same kind, same
    shape — and a value only the TARGET's own vocabulary can judge. Which is
    the whole class of failure that only shows up at run time.
    """
    a, b, col, grp = _setup(client, admin_id, "atom1")
    src_col = _col(client, a, admin_id, id="col_reg", type="dropdown", title="אזור",
                   options=[{"label": "צפון"}, {"label": "דרום"}])
    tgt_col = _col(client, b, admin_id, id="col_side", type="dropdown", title="צד",
                   options=[{"label": "מזרח"}, {"label": "מערב"}])
    r = client.post(f"/api/boards/{a}/automations",
                    json={"actor_id": admin_id, "recipe_id": "created_set_status",
                          "config": {"a_status": "in_progress",
                                     "actions": [{"key": "create_mapped_and_link",
                                                  "values": {"connect": col["id"], "board": b,
                                                             "target_group": grp,
                                                             "text": "ממופה",
                                                             "map": [{"from": src_col["id"],
                                                                      "to": tgt_col["id"]}]}}]}})
    assert r.status_code == 200, r.text
    _item(client, a, admin_id, "מקור", custom_fields={src_col["id"]: "צפון"})
    with Session(cityos_main.engine) as db:
        assert not db.query(Task).filter(Task.board_id == b, Task.title == "ממופה").all(), \
            "an item was created with a field it could not be given"
    runs = _runs(client, a, admin_id)
    assert runs and runs[0]["outcome"] == "failed", runs
    assert "היעד" in (runs[0]["reason"] or ""), runs[0]


def test_a_mapping_that_fits_still_goes_through(client, admin_id):
    a, b, col, grp = _setup(client, admin_id, "atom2")
    src_col = _col(client, a, admin_id, id="col_n1", type="number", title="כמות")
    tgt_col = _col(client, b, admin_id, id="col_n2", type="number", title="כמות יעד")
    client.post(f"/api/boards/{a}/automations",
                json={"actor_id": admin_id, "recipe_id": "created_set_status",
                      "config": {"a_status": "in_progress",
                                 "actions": [{"key": "create_mapped_and_link",
                                              "values": {"connect": col["id"], "board": b,
                                                         "target_group": grp, "text": "ממופה",
                                                         "map": [{"from": src_col["id"],
                                                                  "to": tgt_col["id"]}]}}]}})
    _item(client, a, admin_id, "מקור", custom_fields={src_col["id"]: 7})
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.board_id == b, Task.title == "ממופה").first()
        assert t is not None
        assert str((t.custom_fields or {}).get(tgt_col["id"])) == "7"


# ── מה הלוג שומר ──────────────────────────────────────────────────────────

def test_the_log_keeps_what_was_made_and_where(client, admin_id):
    a, b, col, grp = _setup(client, admin_id, "log1")
    _rule(client, admin_id, a, b, col, grp)
    src = _item(client, a, admin_id, "מקור", priority="high")
    _status(client, src, admin_id, "done")
    run = [r for r in _runs(client, a, admin_id) if r["outcome"] == "ran"][0]
    made = (run.get("result") or {}).get("created") or []
    assert made, run
    one = made[0]
    assert one["task_id"] == _made(b)[0], one
    assert one["board_id"] == b and one["group_id"] == grp, one
    assert one.get("fields") or one.get("map"), "the log does not say what travelled"
    assert run["task_id"] == src and run["event_type"] == "status_changes_to"
    assert (run.get("event") or {}).get("status", "done") == "done"


# ── תלות שבורה והרשאות ────────────────────────────────────────────────────

def _status_of(rid):
    with Session(cityos_main.engine) as db:
        return db.query(Automation).filter(Automation.id == rid).first().status


def test_deleting_the_target_group_suspends_the_rule(client, admin_id):
    a, b, col, grp = _setup(client, admin_id, "dep1")
    rule = _rule(client, admin_id, a, b, col, grp)
    client.post("/api/groups", json={"board_id": b, "name": "אחרת", "actor_id": admin_id})
    client.delete(f"/api/groups/{grp}?user_id={admin_id}")
    _status(client, _item(client, a, admin_id, "מקור"), admin_id, "done")
    assert _status_of(rule["id"]) == "paused_error", _status_of(rule["id"])


def test_the_rule_needs_rights_on_the_target_board(client, admin_id, guinea_id):
    a, b, col, grp = _setup(client, admin_id, "perm1")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    r = client.post(f"/api/boards/{a}/automations",
                    json={"actor_id": guinea_id,
                          "recipe_id": "status_create_in_group_and_link",
                          "config": {"t_status": "done", "a_connect": col["id"],
                                     "a_board": b, "a_target_group": grp,
                                     "a_text": "משימת יעד", "a_fields": ["priority"]}})
    assert r.status_code == 403, r.text


# ── נוסח המשפט ────────────────────────────────────────────────────────────

def test_the_sentence_reads_the_way_the_spec_writes_it(client, admin_id):
    import automations as recipes
    s = recipes.sentence("status_create_in_group_and_link")
    for part in ("כאשר הסטטוס משתנה ל", "צור פריט בשם", "בקבוצה", "בלוח",
                 "העתק", "וקשר אותו לפריט המקור"):
        assert part in s, (part, s)


# ── תתי־פריטים ─────────────────────────────────────────────────────────────

def test_a_subitem_rule_can_act_on_the_subitem_instead_of_the_parent(client, admin_id):
    """«לאפשר עדכון של תת־הפריט, פריט האב או יצירת תת־פריט נוסף» — and the
    default stays the parent, which is what the rules did before the choice."""
    a = _board(client, admin_id, "לוח תת-פריט יעד")
    r = client.post(f"/api/boards/{a}/automations",
                    json={"actor_id": admin_id, "recipe_id": "subitem_done_set_priority",
                          "config": {"a_priority": "critical", "t_on": "subitem"}})
    assert r.status_code == 200, r.text
    parent = _item(client, a, admin_id, "אב")
    sub = _item(client, a, admin_id, "תת", parent_id=parent)
    _status(client, sub, admin_id, "done")
    with Session(cityos_main.engine) as db:
        p = db.query(Task).filter(Task.id == parent).first()
        s = db.query(Task).filter(Task.id == sub).first()
        pk = lambda t: t.priority.value if hasattr(t.priority, "value") else t.priority
        assert pk(s) == "critical", "the rule did not act on the sub-item"
        assert pk(p) != "critical", "it acted on the parent as well"


def test_the_parent_id_reaches_the_action(client, admin_id):
    a = _board(client, admin_id, "לוח מזהה אב")
    client.post(f"/api/boards/{a}/automations",
                json={"actor_id": admin_id, "recipe_id": "subitem_done_set_priority",
                      "config": {"a_priority": "critical"}})
    parent = _item(client, a, admin_id, "אב")
    sub = _item(client, a, admin_id, "תת", parent_id=parent)
    _status(client, sub, admin_id, "done")
    run = [r for r in _runs(client, a, admin_id) if r["outcome"] == "ran"][0]
    with Session(cityos_main.engine) as db:
        row = db.query(AutomationRun).filter(AutomationRun.id == run["id"]).first()
        ev = row.event or {}
    assert ev.get("subitem_id") == sub, ev
    assert ev.get("parent_id") == parent, ev


def test_a_subitem_rule_can_make_another_subitem(client, admin_id):
    a = _board(client, admin_id, "לוח תת נוסף")
    r = client.post(f"/api/boards/{a}/automations",
                    json={"actor_id": admin_id, "recipe_id": "subitem_done_create_subitem",
                          "config": {"a_text": "המשך"}})
    assert r.status_code == 200, r.text
    parent = _item(client, a, admin_id, "אב")
    sub = _item(client, a, admin_id, "תת", parent_id=parent)
    _status(client, sub, admin_id, "done")
    with Session(cityos_main.engine) as db:
        kids = db.query(Task).filter(Task.parent_id == parent).all()
    assert len(kids) == 2, [k.title for k in kids]


def test_the_choice_is_published(client, admin_id):
    d = client.get(f"/api/automation-capabilities?user_id={admin_id}").json()
    assert d["on"]["options"] == ["parent", "subitem"]
    assert d["on"]["default"] == "parent"


def test_a_mapping_is_by_id_and_type_never_by_name(client, admin_id):
    """Two columns on two boards can share a title and hold different things."""
    a, b, col, grp = _setup(client, admin_id, "map1")
    _col(client, a, admin_id, id="col_same_a", type="text", title="אותו שם")
    _col(client, b, admin_id, id="col_same_b", type="number", title="אותו שם")
    r = client.post(f"/api/boards/{a}/automations",
                    json={"actor_id": admin_id, "recipe_id": "created_set_status",
                          "config": {"a_status": "in_progress",
                                     "actions": [{"key": "create_mapped_and_link",
                                                  "values": {"connect": col["id"], "board": b,
                                                             "target_group": grp, "text": "ממופה",
                                                             "map": [{"from": "col_same_a",
                                                                      "to": "col_same_b"}]}}]}})
    assert r.status_code >= 400, "a text column was mapped onto a number column"
