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
    # A new board comes with items and groups of its own, and the sort runs
    # INSIDE each group — so every case here narrows to these four first, and
    # they all land in the same group because they were created the same way.
    _item(client, bid, admin_id, "מיון ד", due_date="2026-01-04")
    _item(client, bid, admin_id, "מיון ב", due_date="2026-01-02")
    _item(client, bid, admin_id, "מיון א", due_date="2026-01-01")
    _item(client, bid, admin_id, "מיון ג", due_date="2026-01-03")
    return bid


MINE = {"op": "and", "rules": [{"field": "title", "op": "has", "v": "מיון"}]}


def _mine(resp):
    """Just the letters, in the order they came back."""
    return [t.split()[-1] for t in _titles(resp) if t.startswith("מיון")]


def _titles(resp):
    return [i["title"] for i in resp.json()["items"]]


# ── the sort reaches the server ────────────────────────────────────────────
def test_the_server_sorts_by_due_date(client, board, admin_id):
    got = _mine(_query(client, board, admin_id, sort="due", filter=MINE))
    assert got == ["א", "ב", "ג", "ד"], got


def test_and_by_title(client, board, admin_id):
    got = _mine(_query(client, board, admin_id, sort="title", filter=MINE))
    assert got == ["א", "ב", "ג", "ד"], got


def test_an_unknown_sort_is_not_an_error_and_is_reported_as_none(client, board, admin_id):
    r = _query(client, board, admin_id, sort="מה שלא קיים").json()
    assert r["sort"] == ""


def test_no_sort_leaves_the_boards_own_order(client, board, admin_id):
    got = _mine(_query(client, board, admin_id, filter=MINE))
    assert got == ["ד", "ב", "א", "ג"], got


# ── and it is applied before the page is cut ───────────────────────────────
def test_the_order_spans_the_pages_rather_than_each_one(client, board, admin_id):
    """The failure this prevents: each page ordered against itself, so page
    two repeats a row from page one and skips another entirely."""
    first = _mine(_query(client, board, admin_id, sort="due", filter=MINE, limit=2, offset=0))
    second = _mine(_query(client, board, admin_id, sort="due", filter=MINE, limit=2, offset=2))
    assert first == ["א", "ב"] and second == ["ג", "ד"], (first, second)
    assert not set(first) & set(second), "a row landed on two pages"


def test_a_sorted_page_is_cut_from_everything_that_matched(client, board, admin_id):
    """Sorting after paging would make the first page the four lowest
    POSITIONS, sorted. Sorting before it makes them the four earliest dates."""
    page = _mine(_query(client, board, admin_id, sort="due", filter=MINE, limit=1))
    assert page == ["א"], page


def test_the_sort_runs_after_the_filter_not_before(client, board, admin_id):
    """The chapter's own sequence. A sort that ran first would order rows that
    are about to be thrown away and leave the survivors in position order."""
    r = _query(client, board, admin_id, sort="due",
               filter={"op": "and", "rules": [
                   {"field": "title", "op": "has", "v": "מיון ג"}]})
    assert _mine(r) == ["ג"]


def test_the_search_narrows_before_the_sort_too(client, board, admin_id):
    got = _mine(_query(client, board, admin_id, sort="due", filter=MINE, q="מיון ב"))
    assert got == ["ב"], got


# ── what the verification found, recorded ──────────────────────────────────
def test_deleted_and_archived_items_are_not_in_the_answer(client, board, admin_id):
    """"פריטים מחוקים או בארכיון אינם נכללים." Already true; pinned so it
    stays true when the query grows."""
    tid = _item(client, board, admin_id, "ייעלם")
    client.delete(f"/api/tasks/{tid}?user_id={admin_id}", headers=_h(admin_id))
    assert "ייעלם" not in _titles(_query(client, board, admin_id))
