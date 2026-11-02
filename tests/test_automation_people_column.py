"""כלל על עמודת "רכזת" מציע את מי שנמצא ב"רכזת".

A board here carries several people columns — אחראי, מנהל פרויקט, רכזת — and
a rule about any of them was offered every member of the board. The member
list is not wrong, it is just not the answer: the question is who is IN that
column, and on a board with forty members the one name that matters sits
somewhere in the middle of the other thirty-nine.

Two sections now, not one filtered list. Nine rules out of ten are about
somebody already in the column; the tenth is written ahead of the first time
anyone is put there, and a rule is forward-looking. Cutting the menu down to
the current occupants would make that tenth rule impossible to write at all,
which is a worse failure than a long menu.

The other half is the action. "עדכן את «רכזת» ל…" asked for a column and
then for "הערך החדש" as a text box, whatever the column was — so writing a
people column meant typing somebody's name exactly right. A typo was a rule
that silently did nothing: _coerce_cell refuses a name it cannot match to a
member of the board, and says so only in the run history, which is not where
anybody looks for a rule that never seemed to run. The value is picked now,
and stored as the name, which is the contract the server already has.

That contract is pinned here too — the browser's picker is only worth
anything if what it stores is what the engine writes.
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from models import Task

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def _board(client, admin_id, name="לוח אנשים"):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _people_col(client, bid, admin_id, title):
    r = client.patch(f"/api/boards/{bid}",
                     json={"actor_id": admin_id,
                           "columns": [{"type": "people", "title": title}]})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json()["columns"] if c["title"] == title)


# ── the contract the picker stores against ─────────────────────────────────

def test_a_rule_writes_a_people_column_from_the_name_it_was_given(
        client, admin_id, member_id):
    """What the picker puts in the blank is a person's name, because that is
    what _coerce_cell matches on. If this ever stops being true the picker
    stores the wrong thing and every such rule quietly skips."""
    bid = _board(client, admin_id)
    cid = _people_col(client, bid, admin_id, "רכזת")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    who = client.get(f"/api/boards/{bid}/members?user_id={admin_id}").json()
    name = next(m["name"] for m in who["members"] if m["user_id"] == member_id)

    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": "created_set_column",
                          "config": {"a_column": cid, "a_text": name}})
    assert r.status_code == 200, r.text
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    with Session(cityos_main.engine) as db:
        cell = (db.query(Task).filter(Task.id == tid).first().custom_fields or {})
    assert cell.get(cid) == [member_id], cell


def test_a_name_that_is_not_a_member_is_refused_rather_than_stored(
        client, admin_id):
    """The reason the blank is a picker: a typo here is a rule that looks
    like it ran and wrote nothing."""
    bid = _board(client, admin_id, "לוח שם שגוי")
    cid = _people_col(client, bid, admin_id, "רכזת")
    client.post(f"/api/boards/{bid}/automations",
                json={"actor_id": admin_id, "recipe_id": "created_set_column",
                      "config": {"a_column": cid, "a_text": "מישהו שלא קיים"}})
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    with Session(cityos_main.engine) as db:
        cell = (db.query(Task).filter(Task.id == tid).first().custom_fields or {})
    assert cid not in cell, cell


# ── the browser's half ─────────────────────────────────────────────────────

def test_the_people_offered_are_the_columns_own():
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  _peopleIn(col){"):]
    fn = fn[:fn.index("\n  },")]
    # read through advCell, which is the one definition of what a cell holds
    assert "advCell(t,f)" in fn, fn
    assert "kind:'people'" in fn, fn


def test_the_board_is_still_reachable_under_a_line():
    """A rule is forward-looking: it may be written about somebody who has
    never been in the column."""
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  _peopleMenu(col,call){"):]
    fn = fn[:fn.index("\n  },")]
    assert "שאר חברי הלוח" in fn, fn
    assert "filter(m=>!n.has(m.user_id))" in fn, fn
    # the flat list the handlers index into is the two sections in order
    assert "const items=mine.concat(rest);" in fn, fn


def test_a_people_target_is_picked_and_not_typed():
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  _targetCol(values,key){"):]
    fn = fn[:fn.index("\n  },")]
    # only the blank that FOLLOWS a column blank, and only set_column pairs them
    assert "/(^|_)text$/" in fn, fn
    assert "values.a_column||values.column" in fn, fn
    # both the rule's own action and an extra one
    assert src.count("_tc&&_tc.type==='people'") == 2, \
        "a caller was added or removed without this test being looked at"


def test_the_whole_chain_in_the_browser(client, admin_id):
    """Driven harness: tests/frontend/automation_people_column.mjs.

    Verified to fail: hand _peopleMenu the board's members unsorted and the
    ordering cases go red; drop the `rest` section and two more do.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_people_column.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
