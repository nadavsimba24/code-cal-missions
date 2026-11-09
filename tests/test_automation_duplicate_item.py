"""שכפול פריט — "כאשר הסטטוס משתנה ל«מוכן לבדיקות», שכפל את הפריט לקבוצה «QA»".

Every creating action this catalog had made an EMPTY item with a name on it.
That is the wrong shape for the hand-off people actually run: an item reaching
«מוכן לבדיקות» and a copy of it — the same values, the same אחראים, the same
columns — opening for QA while the original goes on living its own life. Said
with the old actions, that rule was "צור פריט" plus one "עדכן את העמודה" per
column, re-written by hand every time somebody added a column to the board.

What is pinned here:

  עותק      · the copy carries the item's cells, status, priority, dates and
              אחראים. A "שכפל" that produced a blank row would be create_item
              under a new name
  מילולית   · the cells travel with no mapping, and that is only sound because
              the copy lands on the SAME board — the two rows share a column
              list. The three types that must NOT travel are a mirror and a
              formula (computed elsewhere, so a copy drifts from its source), a
              connect (a relationship, not a value) and a files cell (two cells
              naming one upload)
  פעם אחת   · one copy per source item per rule, ever — the same ledger every
              other creating action keeps. A status that leaves «מוכן לבדיקות»
              and comes back is the same item already handed over
  אין מקור  · the SOURCE item is untouched. A duplicate that edited the thing
              it copied would be the one bug nobody looks for
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import Task


def _board(client, admin_id, name):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _add_cols(client, bid, admin_id, *specs):
    """Append columns to a board and hand back the ones that landed."""
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id, "columns": _cols(client, bid) + list(specs)})
    have = _cols(client, bid)
    return {c["title"]: c for c in have}


def _group(client, bid, admin_id, name):
    r = client.post("/api/groups",
                    json={"board_id": bid, "name": name, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _item(client, bid, admin_id, title, **kw):
    r = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                        "user_id": admin_id, **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _rule(client, bid, admin_id, **over):
    cfg = {"t_status": "review", "a_group": over.pop("group"),
           "a_text": "QA — {{item.name}}"}
    cfg.update(over)
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": "status_duplicate_item",
                          "config": cfg})
    assert r.status_code == 200, r.text
    return r.json()


def _status(client, tid, admin_id, value):
    r = client.patch(f"/api/tasks/{tid}", json={"status": value, "user_id": admin_id})
    assert r.status_code == 200, r.text


def _rows(bid, title):
    with Session(cityos_main.engine) as db:
        return db.query(Task).filter(Task.board_id == bid, Task.title == title,
                                     Task.deleted_at == None).all()          # noqa: E711


def _one(bid, title):
    rows = _rows(bid, title)
    assert len(rows) == 1, f"{len(rows)} rows titled {title}"
    return rows[0]


def _setup(client, admin_id, tag):
    """A board with a QA group and three columns worth copying."""
    bid = _board(client, admin_id, f"פיתוח {tag}")
    qa = _group(client, bid, admin_id, "QA")
    cols = _add_cols(client, bid, admin_id,
                     {"id": f"col_txt_{tag}", "type": "text", "title": "הערות"},
                     {"id": f"col_num_{tag}", "type": "number", "title": "מספר באג"})
    return bid, qa, cols


# ── העותק נושא את הפריט, ולא רק את שמו ─────────────────────────────────────

def test_a_status_change_makes_one_copy_in_the_group_the_rule_names(client, admin_id):
    bid, qa, _ = _setup(client, admin_id, "a")
    _rule(client, bid, admin_id, group=qa)
    tid = _item(client, bid, admin_id, "באג בטופס")
    assert _rows(bid, "QA — באג בטופס") == []
    _status(client, tid, admin_id, "review")
    made = _one(bid, "QA — באג בטופס")
    assert made.group_id == qa
    assert made.id != tid


def test_the_copy_carries_the_items_column_values(client, admin_id):
    bid, qa, cols = _setup(client, admin_id, "b")
    _rule(client, bid, admin_id, group=qa)
    txt, num = cols["הערות"]["id"], cols["מספר באג"]["id"]
    tid = _item(client, bid, admin_id, "דליפה",
                custom_fields={txt: "נבדק בכרום", num: 412})
    _status(client, tid, admin_id, "review")
    made = _one(bid, "QA — דליפה")
    assert made.custom_fields.get(txt) == "נבדק בכרום"
    assert made.custom_fields.get(num) == 412


def test_the_copy_carries_priority_dates_and_description(client, admin_id):
    bid, qa, _ = _setup(client, admin_id, "c")
    _rule(client, bid, admin_id, group=qa)
    tid = _item(client, bid, admin_id, "קריסה", priority="high",
                due_date="2026-12-01T00:00:00", description="נופל בשמירה")
    _status(client, tid, admin_id, "review")
    with Session(cityos_main.engine) as db:
        src = db.query(Task).filter(Task.id == tid).first()
        made = _one(bid, "QA — קריסה")
        assert cityos_main._task_priority_key(made) == cityos_main._task_priority_key(src)
        assert made.due_date == src.due_date
        assert made.description == src.description


def test_the_copy_carries_the_people_the_item_was_assigned_to(client, admin_id, member_id):
    bid, qa, _ = _setup(client, admin_id, "d")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    _rule(client, bid, admin_id, group=qa)
    tid = _item(client, bid, admin_id, "רגרסיה", assignee_ids=[member_id])
    _status(client, tid, admin_id, "review")
    # read inside a session: `assignees` is a lazy relationship, and the row
    # _one hands back is detached the moment its own session closes
    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == bid,
                                     Task.title == "QA — רגרסיה").one()
        assert member_id in [u.id for u in made.assignees]


# ── מה לא עובר, ולמה ───────────────────────────────────────────────────────

def test_a_connect_cell_does_not_travel_to_the_copy(client, admin_id):
    """A copy of an item is not a copy of everyone it was connected to — the
    far item would get a second thing pointing at it that nobody asked for."""
    other = _board(client, admin_id, "לוח שני")
    bid, qa, _ = _setup(client, admin_id, "e")
    cols = _add_cols(client, bid, admin_id,
                     {"id": "col_conn_e", "type": "connect", "title": "מקושר",
                      "connect": {"board_ids": [other], "multiple": True,
                                  "two_way": False}})
    far = _item(client, other, admin_id, "פריט רחוק")
    _rule(client, bid, admin_id, group=qa)
    tid = _item(client, bid, admin_id, "עם קישור",
                custom_fields={cols["מקושר"]["id"]: [far]})
    _status(client, tid, admin_id, "review")
    made = _one(bid, "QA — עם קישור")
    assert cols["מקושר"]["id"] not in (made.custom_fields or {})


def test_a_mirror_cell_does_not_travel_to_the_copy(client, admin_id):
    """A mirror shows a value that lives on another item. Copied, it is a
    number that stops agreeing with its own source the moment either moves."""
    other = _board(client, admin_id, "לוח מראה")
    bid, qa, _ = _setup(client, admin_id, "f")
    cols = _add_cols(client, bid, admin_id,
                     {"id": "col_conn_f", "type": "connect", "title": "מקושר",
                      "connect": {"board_ids": [other], "multiple": False,
                                  "two_way": False}},
                     {"id": "col_mir_f", "type": "mirror", "title": "מראה",
                      "mirror": {"connect": "col_conn_f", "field": "status"}})
    _rule(client, bid, admin_id, group=qa)
    tid = _item(client, bid, admin_id, "עם מראה",
                custom_fields={cols["מראה"]["id"]: "ערך ישן"})
    _status(client, tid, admin_id, "review")
    made = _one(bid, "QA — עם מראה")
    assert cols["מראה"]["id"] not in (made.custom_fields or {})


# ── פעם אחת, והמקור לא נגע ─────────────────────────────────────────────────

def test_a_status_that_leaves_and_comes_back_makes_no_second_copy(client, admin_id):
    bid, qa, _ = _setup(client, admin_id, "g")
    _rule(client, bid, admin_id, group=qa)
    tid = _item(client, bid, admin_id, "חוזר")
    _status(client, tid, admin_id, "review")
    _status(client, tid, admin_id, "in_progress")
    _status(client, tid, admin_id, "review")
    assert len(_rows(bid, "QA — חוזר")) == 1


def test_the_source_item_is_left_exactly_as_it_was(client, admin_id):
    bid, qa, cols = _setup(client, admin_id, "h")
    txt = cols["הערות"]["id"]
    _rule(client, bid, admin_id, group=qa)
    tid = _item(client, bid, admin_id, "מקור", custom_fields={txt: "לא לגעת"})
    before_group = _one(bid, "מקור").group_id
    _status(client, tid, admin_id, "review")
    src = _one(bid, "מקור")
    assert src.id == tid
    assert src.group_id == before_group
    assert (src.custom_fields or {}).get(txt) == "לא לגעת"


# ── הכלל עצמו ──────────────────────────────────────────────────────────────

def test_the_rule_will_not_switch_on_without_a_group(client, admin_id):
    """The group is where the copy lands; a rule missing it has nowhere to
    put anything, and that is a refusal rather than a silent no-op."""
    bid, _, _ = _setup(client, admin_id, "i")
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": "status_duplicate_item",
                          "config": {"t_status": "review", "a_text": "עותק"},
                          "is_active": True})
    assert r.status_code == 400, r.text


def test_a_group_on_another_board_is_skipped_rather_than_copied_into(client, admin_id):
    """The copy is verbatim BECAUSE it stays on one board. A group belonging
    to another board is not a target this action can honour."""
    bid, qa, _ = _setup(client, admin_id, "j")
    elsewhere = _group(client, _board(client, admin_id, "לוח זר"), admin_id, "זרה")
    _rule(client, bid, admin_id, group=elsewhere)
    tid = _item(client, bid, admin_id, "לא ישוכפל")
    _status(client, tid, admin_id, "review")
    assert _rows(bid, "QA — לא ישוכפל") == []
