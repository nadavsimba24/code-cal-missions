"""מיון, מבנה עמודות ומונים — מה המיון מותר לעשות, ומה המספרים אומרים.

Three rules that each prevent a different kind of quiet wrongness.

THE SORT runs inside the groups. A flat sort reorders the whole board and the
groups dissolve — rows from three of them interleave by due date and the board
stops being the thing somebody arranged it into. Groups are structure, not a
result, so they keep the order the board gives them and the sort decides who
sits where inside each one. Sub-items get the same order under their parent,
because a sort that reordered items and left their children in position order
would be two orders on one screen.

A COLUMN is referenced by its id, so renaming one cannot break a view. What
happens when one is DELETED depends on what the view was using it for, and the
difference is the point: a column that was only being shown is simply no
longer shown, while a column the view FILTERS or SORTS by leaves the view
needing a fix. Silently dropping either would answer a different question than
the tab promises — wider rows, or a different order — with nothing on screen
saying so.

THE COUNTERS are three numbers, not one. Top-level items that matched,
sub-items that matched, and rows present only as context. A context row is not
a result, and counting it as one overstates the answer by exactly the rows that
did not qualify.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import Group, SavedView  # noqa: E402

from test_saved_views import CUT, _board, _mk, _list  # noqa: E402
from test_view_hierarchy import _item, _query, _on, _row, _h  # noqa: E402


def _group(client, bid, uid, name):
    """POST /api/groups, not /api/boards/{id}/groups — the board-scoped path
    does not exist and answered 405, which the first version of this helper
    read as "the fixture is broken" rather than "the URL is wrong"."""
    r = client.post("/api/groups", json={"board_id": bid, "user_id": uid, "name": name},
                    headers=_h(uid))
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── the sort stays inside the groups ───────────────────────────────────────
@pytest.fixture
def grouped(client, admin_id):
    """Two groups, each holding items whose due dates interleave with the
    other group's — so a flat sort and a per-group sort differ visibly."""
    bid = _board(client, admin_id)
    g1 = _group(client, bid, admin_id, "קבוצה א")
    g2 = _group(client, bid, admin_id, "קבוצה ב")
    _item(client, bid, admin_id, "מיון א2", group_id=g1, due_date="2026-01-02")
    _item(client, bid, admin_id, "מיון א1", group_id=g1, due_date="2026-01-04")
    _item(client, bid, admin_id, "מיון ב2", group_id=g2, due_date="2026-01-01")
    _item(client, bid, admin_id, "מיון ב1", group_id=g2, due_date="2026-01-03")
    return {"bid": bid, "g1": g1, "g2": g2}


def _order(r):
    return [i["title"] for i in r["items"] if i["title"].startswith("מיון")]


def test_the_sort_runs_inside_each_group(client, grouped, admin_id):
    r = _query(client, grouped["bid"], admin_id, sort="due", filter=_on("מיון"))
    got = _order(r)
    assert got == ["מיון א2", "מיון א1", "מיון ב2", "מיון ב1"], got


def test_and_does_not_interleave_the_groups(client, grouped, admin_id):
    """A flat sort by due date would give ב2, א2, ב1, א1 — the groups gone."""
    got = _order(_query(client, grouped["bid"], admin_id, sort="due", filter=_on("מיון")))
    first_b = next(i for i, t in enumerate(got) if t.startswith("מיון ב"))
    assert all(t.startswith("מיון א") for t in got[:first_b]), got
    assert all(t.startswith("מיון ב") for t in got[first_b:]), got


def test_the_groups_keep_the_boards_own_order(client, grouped, admin_id):
    """Sorting never reorders the groups themselves."""
    for key in ("due", "title", ""):
        got = _order(_query(client, grouped["bid"], admin_id, sort=key, filter=_on("מיון")))
        assert got[0].startswith("מיון א"), (key, got)


def test_sub_items_are_sorted_under_their_parent(client, admin_id):
    """Otherwise the items follow one order and their children another."""
    bid = _board(client, admin_id)
    parent = _item(client, bid, admin_id, "הורה סימן")
    _item(client, bid, admin_id, "ילד סימן ג", parent=parent, due_date="2026-01-03")
    _item(client, bid, admin_id, "ילד סימן א", parent=parent, due_date="2026-01-01")
    _item(client, bid, admin_id, "ילד סימן ב", parent=parent, due_date="2026-01-02")

    r = _query(client, bid, admin_id, sort="due", filter=_on("סימן"))
    kids = [s["title"] for s in _row(r, "הורה סימן")["subtasks"]]
    assert kids == ["ילד סימן א", "ילד סימן ב", "ילד סימן ג"], kids


def test_the_hierarchy_is_not_flattened_by_sorting(client, admin_id):
    """Sub-items stay under their parent — they never become rows of their
    own, whatever the order asks for."""
    bid = _board(client, admin_id)
    parent = _item(client, bid, admin_id, "הורה סימן", due_date="2026-12-31")
    kid = _item(client, bid, admin_id, "ילד סימן", parent=parent, due_date="2026-01-01")
    r = _query(client, bid, admin_id, sort="due", filter=_on("סימן"))
    assert all(i["id"] != kid for i in r["items"]), "a sub-item was promoted to a row"
    assert [s["title"] for s in _row(r, "הורה סימן")["subtasks"]] == ["ילד סימן"]


# ── the three counters ─────────────────────────────────────────────────────
def test_the_counters_are_three_different_numbers(client, admin_id):
    bid = _board(client, admin_id)
    hit = _item(client, bid, admin_id, "הורה סימן")
    _item(client, bid, admin_id, "ילד סימן א", parent=hit)
    ctx = _item(client, bid, admin_id, "הורה רגיל")
    _item(client, bid, admin_id, "ילד סימן ב", parent=ctx)
    _item(client, bid, admin_id, "הורה אחר")

    r = _query(client, bid, admin_id, filter=_on("סימן"))
    assert r["matched_own"] == 1, "top-level items that matched"
    assert r["matched_subs"] == 2, "sub-items that matched"
    assert r["matched_context"] == 1, "rows present only as context"


def test_a_context_row_is_not_counted_as_a_match(client, admin_id):
    """"אין לספור אב שאינו מתאים כאילו הוא תוצאת התאמה."""
    bid = _board(client, admin_id)
    ctx = _item(client, bid, admin_id, "הורה רגיל")
    _item(client, bid, admin_id, "ילד סימן", parent=ctx)
    r = _query(client, bid, admin_id, filter=_on("סימן"))
    assert r["matched_own"] == 0, "a row that did not match was counted as one"
    assert r["matched_context"] == 1 and r["matched_subs"] == 1


def test_the_counters_are_not_computed_from_the_loaded_page(client, admin_id):
    """"או לחשב מונים רק מהעמוד שכבר נטען." A page of one must not report one."""
    bid = _board(client, admin_id)
    for i in range(5):
        _item(client, bid, admin_id, f"הורה סימן {i}")
    r = _query(client, bid, admin_id, filter=_on("סימן"), limit=1)
    assert len(r["items"]) == 1
    assert r["matched_own"] == 5, r["matched_own"]
    assert r["matched"] == 5


# ── columns: renamed, hidden, deleted ──────────────────────────────────────
def _column(client, bid, admin_id, title, type_="text"):
    cur = client.get(f"/api/boards/{bid}?user_id={admin_id}",
                     headers=_h(admin_id)).json().get("columns") or []
    r = client.patch(f"/api/boards/{bid}",
                     json={"user_id": admin_id,
                           "columns": list(cur) + [{"type": type_, "title": title}]},
                     headers=_h(admin_id))
    assert r.status_code == 200, r.text
    return r.json()["columns"][-1]["id"]


def test_renaming_a_column_does_not_break_a_view(client, admin_id):
    """"הפניות לעמודות נשמרות לפי מזהה יציב. שינוי שם אינו שובר תצוגה."""
    bid = _board(client, admin_id)
    col = _column(client, bid, admin_id, "תקציב")
    vid = _mk(client, bid, admin_id, "לפי תקציב",
              filters=dict(CUT, adv={"op": "and", "rules": [
                  {"field": col, "op": "gt", "v": 0}]})).json()["id"]

    cur = client.get(f"/api/boards/{bid}?user_id={admin_id}",
                     headers=_h(admin_id)).json()["columns"]
    for c in cur:
        if c["id"] == col:
            c["title"] = "תקציב מאושר"
    assert client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": cur},
                        headers=_h(admin_id)).status_code == 200

    v = [x for x in _list(client, bid, admin_id) if x["id"] == vid][0]
    assert v["needs_fix"] == [], "a rename broke the view"
    assert v["filters"]["adv"]["rules"][0]["field"] == col


def test_deleting_a_column_a_view_only_SHOWS_does_not_need_fixing(client, admin_id):
    """"מחיקת עמודת תצוגה רגילה תסיר אותה מההצגה" — and nothing more."""
    bid = _board(client, admin_id)
    col = _column(client, bid, admin_id, "הערה")
    vid = _mk(client, bid, admin_id, "עם הערה",
              filters=dict(CUT, cols={"order": ["item", col], "widths": {col: 150}})).json()["id"]
    client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": []},
                 headers=_h(admin_id))
    v = [x for x in _list(client, bid, admin_id) if x["id"] == vid][0]
    assert v["needs_fix"] == [], v["needs_fix"]


def test_deleting_a_column_a_view_SORTS_by_needs_fixing(client, admin_id):
    """The same failure as the filter case in different clothes: the view
    opens, rows come back in some order, and nothing says the order it
    promised is not the order it gave."""
    bid = _board(client, admin_id)
    col = _column(client, bid, admin_id, "תקציב", type_="number")
    vid = _mk(client, bid, admin_id, "ממוין לפי תקציב",
              filters=dict(CUT, sort=col)).json()["id"]
    assert [x for x in _list(client, bid, admin_id)
            if x["id"] == vid][0]["needs_fix"] == []

    client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": []},
                 headers=_h(admin_id))
    v = [x for x in _list(client, bid, admin_id) if x["id"] == vid][0]
    assert v["needs_fix"] == [col], v["needs_fix"]


def test_the_built_in_sorts_are_never_reported_as_missing(client, admin_id):
    bid = _board(client, admin_id)
    for key in ("due", "priority", "title"):
        vid = _mk(client, bid, admin_id, f"ממוין {key}", filters=dict(CUT, sort=key)).json()["id"]
        v = [x for x in _list(client, bid, admin_id) if x["id"] == vid][0]
        assert v["needs_fix"] == [], (key, v["needs_fix"])


def test_hiding_a_column_in_a_view_leaves_it_on_the_board(client, admin_id):
    """"הסתרת עמודה בתצוגה אינה מוחקת אותה מהלוח."""
    bid = _board(client, admin_id)
    col = _column(client, bid, admin_id, "הערה")
    _mk(client, bid, admin_id, "בלי הערה", filters=dict(CUT, cols={"hidden": [col]}))
    cols = client.get(f"/api/boards/{bid}?user_id={admin_id}",
                      headers=_h(admin_id)).json()["columns"]
    assert any(c["id"] == col for c in cols), "hiding a column deleted it"
