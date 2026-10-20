"""יציאה, איפוס ורענון — מה החיפוש הוא, ומה שינוי זמני לא קונה.

Almost all of this chapter is the screen's: leaving a view, leaving the board
or reloading drops the temporary adjustments, and nothing personal survives a
visit. The server's share is that there is nothing for it to drop — covered by
tests/test_view_config_scope.py — plus two sentences it has to keep itself.

  "חיפוש הוא שכבת צמצום זמנית מעל מסנני התצוגה." On top of, not instead of.
    The two are ANDed, so clearing the search leaves the saved filter doing
    exactly what it did. A search that replaced the filter would quietly widen
    the board the moment somebody typed in the box — and widen it further the
    moment they cleared it.

  "שינוי זמני של תנאי הסינון לא מעניק גישה לפריטים או לעמודות חסומים." A
    filter is a question about rows, and an answer is rows. Neither the item
    permissions nor the column ones are relaxed because the question was typed
    rather than saved — which matters because a temporary filter is the one
    place somebody can write a condition by hand.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import BoardViewPrefs, Task  # noqa: E402

from test_saved_views import CUT, _board, _mk, _cfg  # noqa: E402
from test_view_column_permissions import _column, _deny  # noqa: E402


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _item(client, bid, uid, title, **extra):
    r = client.post("/api/tasks", json=dict({"board_id": bid, "title": title,
                                             "user_id": uid}, **extra), headers=_h(uid))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _hide(client, tid, admin_id, uid):
    """Item permissions have a door of their own; PATCH /api/tasks ignores the
    field entirely, so setting it there looked like it worked and hid nothing."""
    r = client.post(f"/api/tasks/{tid}/permissions",
                    json={"actor_id": admin_id, "user_id": uid, "perm": "none"},
                    headers=_h(admin_id))
    assert r.status_code == 200, r.text


def _query(client, bid, uid, **body):
    return client.post(f"/api/boards/{bid}/items/query",
                       json=dict({"user_id": uid, "today": "2026-10-20",
                                  "tz_offset": 180}, **body), headers=_h(uid))


OPEN_ONLY = {"op": "and", "rules": [{"field": "status", "op": "ne", "v": "done"}]}


# ── the search narrows, it does not replace ────────────────────────────────
@pytest.fixture
def board(client, admin_id):
    """A new board is not an empty one — it comes with items of its own, and
    the first version of these cases counted as though it did not."""
    bid = _board(client, admin_id)
    for t in ("מדרכה שבורה", "מדרכה חדשה", "גדר שבורה"):
        _item(client, bid, admin_id, t)
    return bid


def test_the_search_sits_on_top_of_the_filter(client, board, admin_id):
    """Both, ANDed — not one or the other."""
    only_filter = _query(client, board, admin_id, filter=OPEN_ONLY).json()
    assert only_filter["matched"] >= 3

    both = _query(client, board, admin_id, filter=OPEN_ONLY, q="מדרכה").json()
    assert both["matched"] == 2, both["matched"]
    assert both["conditions"] == 1, "the filter stopped being applied"
    assert both["matched"] < only_filter["matched"], "the search narrowed nothing"


def test_clearing_the_search_leaves_the_filter_doing_what_it_did(client, board, admin_id):
    base = _query(client, board, admin_id, filter=OPEN_ONLY).json()["matched"]
    with_q = _query(client, board, admin_id, filter=OPEN_ONLY, q="גדר").json()
    assert with_q["matched"] == 1
    cleared = _query(client, board, admin_id, filter=OPEN_ONLY, q="").json()
    assert cleared["matched"] == base and cleared["conditions"] == 1


def test_a_search_alone_does_not_invent_a_filter(client, board, admin_id):
    r = _query(client, board, admin_id, q="מדרכה").json()
    assert r["matched"] == 2 and r["conditions"] == 0


def test_a_search_cannot_widen_the_answer(client, board, admin_id):
    """The failure a replace would cause: typing in the box showing MORE than
    the filter alone did."""
    base = _query(client, board, admin_id, filter=OPEN_ONLY).json()["matched"]
    for text in ("", "מדרכה", "שבורה", "לא קיים"):
        got = _query(client, board, admin_id, filter=OPEN_ONLY, q=text).json()["matched"]
        assert got <= base, f"{text!r} widened the answer to {got}"


# ── a temporary filter buys no access ──────────────────────────────────────
def test_a_typed_filter_does_not_reach_items_somebody_may_not_see(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    open_tid = _item(client, bid, admin_id, "גלוי")
    hidden = _item(client, bid, admin_id, "חסוי")
    _hide(client, hidden, admin_id, guinea_id)

    got = _query(client, bid, guinea_id, filter=OPEN_ONLY).json()
    titles = [i["title"] for i in got["items"]]
    assert "חסוי" not in titles and "גלוי" in titles, titles
    assert hidden not in got["item_ids"] and open_tid in got["item_ids"]


def test_nor_by_asking_about_it_directly(client, admin_id, guinea_id):
    """Naming the item in the condition is the sharpest form of the attempt:
    the answer to "which rows match" must still not include it."""
    bid = _board(client, admin_id, invite=[guinea_id])
    hidden = _item(client, bid, admin_id, "חסוי")
    _hide(client, hidden, admin_id, guinea_id)
    got = _query(client, bid, guinea_id,
                 filter={"op": "and", "rules": [
                     # "has", not "contains" — the operator set is small and
                     # closed, and an unknown one is a 400 rather than a filter
                     {"field": "title", "op": "has", "v": "חסוי"}]}).json()
    assert got["matched"] == 0 and got["item_ids"] == []


def test_a_typed_filter_does_not_reach_a_column_somebody_may_not_see(client, admin_id, guinea_id):
    """The column half. Reported as denied rather than answered — and under
    the blocking policy, refused outright."""
    bid = _board(client, admin_id, invite=[guinea_id])
    col = _column(client, bid, admin_id)
    _item(client, bid, admin_id, "פריט")
    _deny(client, bid, admin_id, col, guinea_id)

    got = _query(client, bid, guinea_id,
                 filter={"op": "and", "rules": [{"field": col, "op": "gt", "v": 0}]}).json()
    assert got["denied_fields"] == [col], got
    assert got["conditions"] == 0, "the rule about a forbidden column was run"


# ── nothing personal survives a visit ──────────────────────────────────────
def test_nothing_temporary_is_kept_per_person_between_visits(client, admin_id):
    """"אין שמירת מצב זמני אישית בין ביקורים." What IS kept per person is two
    things, both of them deliberate and neither of them temporary state: the
    order of the unpinned views, and which view they were last on. This case
    fails if a third ever joins them quietly."""
    cols = {c.name for c in BoardViewPrefs.__table__.columns}
    assert cols == {"id", "board_id", "user_id", "order", "last_view_id", "updated_at"}, cols


def test_an_explicit_reset_gets_the_current_shared_configuration(client, admin_id):
    """"פעולה מפורשת של איפוס שינויים זמניים תחזיר לתצורה המשותפת העדכנית" —
    the screen re-reads the strip, so the strip has to be the live answer and
    not what it was when the board was opened."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה",
              filters=dict(CUT, cols={"widths": {"item": 200}})).json()["id"]
    _cfg(client, vid, admin_id, dict(CUT, cols={"widths": {"item": 400}}))
    r = client.get(f"/api/boards/{bid}/views?user_id={admin_id}", headers=_h(admin_id))
    fresh = [v for v in r.json()["views"] if v["id"] == vid][0]
    assert fresh["filters"]["cols"]["widths"]["item"] == 400
