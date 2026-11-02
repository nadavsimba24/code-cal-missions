"""חלון הסינון מציע בדיוק את עמודות הלוח — לא פחות, ולא עמודות שאינן שם.

Two faults found on a real board, opposite in direction and both in the one
list the filter builds from.

  · A column taken OFF the board went on being offered. The five built-ins
    were added to that list unconditionally, so a board whose admin had used
    the header's own "מחק עמודה" on סטטוס, עדיפות, אחראים or תאריך יעד still
    showed them in the filter — a question about a column the board does not
    draw, which from the person's side is a column that does not exist.
  · מזהה פריט was never offered on ANY board. It is an automatic column every
    board is issued on creation, so this was fifteen boards out of fifteen.
    Nothing was missing underneath it: the board filter already feeds
    _derived_cells beside the item's own cells, and the automations could ask
    about it. It was absent from filter_ast.KINDS alone.

The third thing here is the one that would have hurt most quietly: a saved
view filtering on a column since removed must report it as REMOVED. Reported
as "no permission", a board running filter_column_policy='block' refuses to
open the view at all — locking somebody out of their own saved cut over a
permission nobody had taken away.
"""
import pathlib
import re

from sqlalchemy.orm import Session

import filter_ast
import main as cityos_main
from models import Board

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def _adv_kinds():
    """ADV_KINDS as the browser holds it."""
    src = INDEX.read_text(encoding="utf-8")
    body = src[src.index("const ADV_KINDS = {"):]
    body = body[:body.index("};")]
    return set(re.findall(r"(\w+)\s*:\s*'", body))


def test_the_two_type_tables_still_agree():
    """The browser decides what to offer and the server decides what it can
    answer. A type in one and not the other is a column that is either offered
    and refused, or answerable and never asked."""
    assert _adv_kinds() == set(filter_ast.KINDS), \
        _adv_kinds().symmetric_difference(set(filter_ast.KINDS))


def test_the_item_id_column_can_be_filtered_by(client, admin_id):
    """מזהה פריט is on every board and was offered on none of them."""
    assert filter_ast.KINDS.get("item_id") == "text"
    assert "item_id" in _adv_kinds()
    bid = client.post("/api/boards",
                      json={"name": "לוח מזהה", "user_id": admin_id}).json()["id"]
    col = client.patch(f"/api/boards/{bid}",
                       json={"user_id": admin_id,
                             "columns": [{"type": "item_id", "title": "מספר מזהה"}]}
                       ).json()["columns"][0]
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    uid = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"][0]["item_uid"]
    # the value the filter will be asked about is the one the board shows
    assert uid
    rule = {"type": "group", "operator": "and", "rules": [
        {"type": "rule", "field": col["id"], "operator": "eq", "value": str(uid)}]}
    d = client.post(f"/api/boards/{bid}/items/query?user_id={admin_id}",
                    json={"filter": rule})
    assert d.status_code == 200, d.text
    assert [i["id"] for i in d.json()["items"]] == [tid], d.json()
    # and a different id answers with nothing, so the rule is doing the asking
    rule["rules"][0]["value"] = str(uid) + "0"
    d = client.post(f"/api/boards/{bid}/items/query?user_id={admin_id}",
                    json={"filter": rule})
    assert d.json()["items"] == [], d.json()


# ── the browser's own list ──────────────────────────────────────────────────

def test_a_column_taken_off_the_board_is_not_offered():
    """advFields() is the one list both the quick panel and the builder read."""
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("function advFields()"):]
    fn = fn[:fn.index("\nfunction ")]
    # the built-ins are filtered, and "שם הפריט" is deliberately exempt
    assert "advColGone" in fn, fn
    assert "f.id==='title'||!gone(f.id)" in fn, fn
    # a custom column is dropped for permission only: it cannot be hidden
    # (see HIDEABLE_BUILTIN_COLS), it is removed from the board's own list,
    # so a second guard here would be a line that can never run
    assert "if(advColHidden(c.id)) return;" in fn, fn
    assert "gone(c.id)" not in fn, "a guard that cannot fire is back in advFields"


def test_removed_is_told_apart_from_denied():
    """The message decides whether a view opens at all."""
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("function advKnownField(id)"):]
    fn = fn[:fn.index("\nconst advField")]
    assert "if(advColGone(id))return false;" in fn, fn
    # the branch this protects
    assert "filter_column_policy)==='block' && pruned.denied.length" in src


def test_col_gone_reads_the_boards_own_hidden_list():
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("function advColGone(colId)"):]
    fn = fn[:fn.index("}")]
    assert "col_hidden" in fn, fn


def test_hiding_a_builtin_is_what_the_header_menu_writes(client, admin_id):
    """The link between the two: "מחק עמודה" on a built-in header writes
    col_hidden, which is exactly what the filter now consults."""
    bid = client.post("/api/boards",
                      json={"name": "לוח הסתרה", "user_id": admin_id}).json()["id"]
    r = client.patch(f"/api/boards/{bid}",
                     json={"user_id": admin_id, "col_hidden": ["status", "due"]})
    assert r.status_code == 200, r.text
    d = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    assert set(d["col_hidden"]) == {"status", "due"}


# ── and the server makes the same call ──────────────────────────────────────

def test_the_server_stops_offering_a_builtin_the_board_hid(client, admin_id):
    """_filter_columns says in as many words that the two sides disagreeing is
    a leak rather than a bug. The browser now drops a removed column; so must
    the query endpoint.

    Only the four built-ins can be in col_hidden — update_board refuses any
    other id — which is why these were the only ghosts found on real boards.
    A custom column is removed by actually leaving settings["columns"], so it
    disappears from both sides on its own.
    """
    bid = client.post("/api/boards",
                      json={"name": "לוח מוסתר", "user_id": admin_id}).json()["id"]
    client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                    "user_id": admin_id})

    def matched(field, op):
        return client.post(
            f"/api/boards/{bid}/items/query?user_id={admin_id}",
            json={"filter": {"type": "group", "operator": "and", "rules": [
                {"type": "rule", "field": field, "operator": op}]}}
        ).json()["matched"]

    total = matched("status", "filled")
    assert total >= 1
    # every item carries a status, so "ריק" answers with none of them — which
    # is only true while the rule is actually being run
    assert matched("status", "empty") == 0

    r = client.patch(f"/api/boards/{bid}",
                     json={"user_id": admin_id, "col_hidden": ["status"]})
    assert r.status_code == 200, r.text
    # the rule is pruned now, so the filter is empty and everything comes back
    assert matched("status", "empty") == total, \
        "the server still answers a filter on a column the board no longer draws"


def test_only_the_four_builtins_can_be_hidden(client, admin_id):
    """The constraint both fixes rest on.

    Because only these four can be hidden, neither advFields() in the browser
    nor _filter_columns here needs a guard for a hidden CUSTOM column — such a
    column leaves the board's own list instead. Widening HIDEABLE_BUILTIN_COLS
    would make that true no longer, silently, in two files at once. If this
    fails, that is what to go and do.
    """
    assert cityos_main.HIDEABLE_BUILTIN_COLS == frozenset(
        {"assignees", "status", "priority", "due"}), (
        "HIDEABLE_BUILTIN_COLS widened — advFields() in frontend/index.html and "
        "_filter_columns in backend/main.py each need a hidden-column guard back")
    bid = client.post("/api/boards",
                      json={"name": "לוח כללים", "user_id": admin_id}).json()["id"]
    col = client.patch(f"/api/boards/{bid}",
                       json={"user_id": admin_id,
                             "columns": [{"type": "text", "title": "הערה"}]}
                       ).json()["columns"][0]
    client.patch(f"/api/boards/{bid}",
                 json={"user_id": admin_id,
                       "col_hidden": ["status", "priority", "assignees", "due",
                                      "title", col["id"]]})
    got = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["col_hidden"]
    assert set(got) == {"status", "priority", "assignees", "due"}, got


def test_a_deleted_custom_column_leaves_the_filter_by_itself(client, admin_id):
    """The other half of "מה שנמחק אין צורך שיופיע": a custom column is not
    hidden, it is removed from the board's own list, so neither side can go on
    offering it."""
    bid = client.post("/api/boards",
                      json={"name": "לוח מחיקה", "user_id": admin_id}).json()["id"]
    col = client.patch(f"/api/boards/{bid}",
                       json={"user_id": admin_id,
                             "columns": [{"type": "text", "title": "הערה"}]}
                       ).json()["columns"][0]
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        assert col["id"] in cityos_main._filter_columns(b, admin_id, "admin")[1]
    client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": []})
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        known, fields = cityos_main._filter_columns(b, admin_id, "admin")
        assert col["id"] not in fields and col["id"] not in known
