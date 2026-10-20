"""שימוש במנגנון הקיים — אימות לפני פיתוח, ומה שהאימות מצא.

The chapter asks for one thing before any code: verify that the existing
filter mechanism can apply conditions to sub-items. It also states that
filtering and sorting apply to all permitted board data "גם בטעינה מדורגת".

Both were checked against the code, and both answers were no.

SORT was the browser's alone. Below the client threshold that is every row and
nobody could tell; past it the server answers with a PAGE, and sorting a page
is not sorting the board — it orders fifty rows that were chosen by position
and calls the result sorted. Page two then repeats rows and skips others,
because each page is ordered against itself. Fixed here: the order is applied
after the filter and before the page is cut, which is also the sequence the
chapter gives — permissions, conditions and search, sort, hierarchy.

SUB-ITEMS were not reached by the mechanism at all — the query evaluated rows
with no parent and nothing else. That gap is closed, and the rules it is
closed by live in tests/test_view_hierarchy.py.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import Task  # noqa: E402,F401

from test_saved_views import _board  # noqa: E402


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _item(client, bid, uid, title, **extra):
    r = client.post("/api/tasks", json=dict({"board_id": bid, "title": title,
                                             "user_id": uid}, **extra), headers=_h(uid))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _query(client, bid, uid, **body):
    return client.post(f"/api/boards/{bid}/items/query",
                       json=dict({"user_id": uid, "today": "2026-10-20",
                                  "tz_offset": 180}, **body), headers=_h(uid))


@pytest.fixture
def board(client, admin_id):
    """Four items whose due dates are deliberately not in position order."""
    bid = _board(client, admin_id)
    _item(client, bid, admin_id, "ד", due_date="2026-01-04")
    _item(client, bid, admin_id, "ב", due_date="2026-01-02")
    _item(client, bid, admin_id, "א", due_date="2026-01-01")
    _item(client, bid, admin_id, "ג", due_date="2026-01-03")
    return bid


def _titles(resp):
    return [i["title"] for i in resp.json()["items"]]


# ── the sort reaches the server ────────────────────────────────────────────
def test_the_server_sorts_by_due_date(client, board, admin_id):
    got = [t for t in _titles(_query(client, board, admin_id, sort="due")) if t in "אבגד"]
    assert got == ["א", "ב", "ג", "ד"], got


def test_and_by_title(client, board, admin_id):
    got = [t for t in _titles(_query(client, board, admin_id, sort="title")) if t in "אבגד"]
    assert got == ["א", "ב", "ג", "ד"], got


def test_an_unknown_sort_is_not_an_error_and_is_reported_as_none(client, board, admin_id):
    r = _query(client, board, admin_id, sort="מה שלא קיים").json()
    assert r["sort"] == ""


def test_no_sort_leaves_the_boards_own_order(client, board, admin_id):
    got = [t for t in _titles(_query(client, board, admin_id)) if t in "אבגד"]
    assert got == ["ד", "ב", "א", "ג"], got


# ── and it is applied before the page is cut ───────────────────────────────
def test_the_order_spans_the_pages_rather_than_each_one(client, board, admin_id):
    """The failure this prevents: each page ordered against itself, so page
    two repeats a row from page one and skips another entirely."""
    first = _titles(_query(client, board, admin_id, sort="due", limit=2, offset=0))
    second = _titles(_query(client, board, admin_id, sort="due", limit=2, offset=2))
    both = [t for t in first + second if t in "אבגד"]
    assert both == sorted(both), both
    assert len(set(first) & set(second)) == 0, "a row landed on two pages"


def test_a_sorted_page_is_cut_from_everything_that_matched(client, board, admin_id):
    """Sorting after paging would make the first page the four lowest
    POSITIONS, sorted. Sorting before it makes them the four earliest dates."""
    page = [t for t in _titles(_query(client, board, admin_id, sort="due", limit=1))
            if t in "אבגד"]
    assert page == ["א"], page


def test_the_sort_runs_after_the_filter_not_before(client, board, admin_id):
    """The chapter's own sequence. A sort that ran first would order rows that
    are about to be thrown away and leave the survivors in position order."""
    r = _query(client, board, admin_id, sort="due",
               filter={"op": "and", "rules": [
                   {"field": "title", "op": "has", "v": "ג"}]})
    assert [t for t in _titles(r) if t in "אבגד"] == ["ג"]


def test_the_search_narrows_before_the_sort_too(client, board, admin_id):
    got = [t for t in _titles(_query(client, board, admin_id, sort="due", q="ב"))
           if t in "אבגד"]
    assert got == ["ב"], got


# ── what the verification found, recorded ──────────────────────────────────
def test_deleted_and_archived_items_are_not_in_the_answer(client, board, admin_id):
    """"פריטים מחוקים או בארכיון אינם נכללים." Already true; pinned so it
    stays true when the query grows."""
    tid = _item(client, board, admin_id, "ייעלם")
    client.delete(f"/api/tasks/{tid}?user_id={admin_id}", headers=_h(admin_id))
    got = _query(client, board, admin_id).json()
    assert tid not in got["item_ids"] if "item_ids" in got else True
    assert "ייעלם" not in _titles(_query(client, board, admin_id))
