"""הצמדה, סדר וקישורים — איפה התצוגות יושבות, ולאן כניסה רגילה נוחתת.

Two orders, belonging to two people, and the whole of this chapter is keeping
them from reaching into each other:

  the board owner decides WHICH views are pinned and how the pinned ones sit.
    That is a statement about the board — these are the cuts that matter here.
  everybody else arranges the rest for themselves. Which tab somebody reaches
    for first is a habit, and it is saved on the server rather than in the
    browser so it is waiting on the next machine they sign in from.

And one thing that is deliberately NOT derived from either: where a normal
entry lands. That is the view this person was last on — not the first pinned
one, because a board owner pinning a cut must not silently move everybody's
landing place, and not the first tab on the strip either.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import BoardViewPrefs  # noqa: E402

from test_saved_views import CUT, _board, _mk, _list  # noqa: E402
from test_view_column_permissions import _column, _cut_on, _deny  # noqa: E402


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _patch(client, vid, uid, **data):
    return client.patch(f"/api/views/{vid}", json=dict(data, user_id=uid), headers=_h(uid))


def _strip(client, bid, uid):
    r = client.get(f"/api/boards/{bid}/views?user_id={uid}", headers=_h(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _order(client, bid, uid, ids):
    return client.put(f"/api/boards/{bid}/views/order",
                      json={"user_id": uid, "order": ids}, headers=_h(uid))


def _last(client, bid, uid, vid):
    return client.put(f"/api/boards/{bid}/views/last",
                      json={"user_id": uid, "view_id": vid}, headers=_h(uid))


# ── unpinning puts it back where the unpinned live ─────────────────────────
def test_unpinning_returns_a_view_to_the_unpinned_area(client, admin_id):
    bid = _board(client, admin_id)
    a = _mk(client, bid, admin_id, "א").json()["id"]
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    _mk(client, bid, admin_id, "ג")

    _patch(client, b, admin_id, pinned=True)
    assert [v["name"] for v in _strip(client, bid, admin_id)["views"]][0] == "ב"

    _patch(client, b, admin_id, pinned=False)
    names = [v["name"] for v in _strip(client, bid, admin_id)["views"]]
    assert names == ["א", "ב", "ג"], names
    assert a


def test_unpinning_restores_the_readers_own_arrangement(client, admin_id, guinea_id):
    """Their order was never gone — the pin was in front of it."""
    bid = _board(client, admin_id, invite=[guinea_id])
    a = _mk(client, bid, admin_id, "א").json()["id"]
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    _order(client, bid, guinea_id, [b, a])
    assert [v["name"] for v in _strip(client, bid, guinea_id)["views"]] == ["ב", "א"]

    _patch(client, a, admin_id, pinned=True)
    assert [v["name"] for v in _strip(client, bid, guinea_id)["views"]] == ["א", "ב"]
    _patch(client, a, admin_id, pinned=False)
    assert [v["name"] for v in _strip(client, bid, guinea_id)["views"]] == ["ב", "א"]


def test_the_owner_orders_the_pinned_ones_among_themselves(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    a = _mk(client, bid, admin_id, "א").json()["id"]
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    for vid in (a, b):
        _patch(client, vid, admin_id, pinned=True)
    assert [v["name"] for v in _strip(client, bid, guinea_id)["views"]] == ["א", "ב"]

    _patch(client, b, admin_id, position=-1)        # ahead of א
    assert [v["name"] for v in _strip(client, bid, guinea_id)["views"]] == ["ב", "א"]


# ── the personal order travels with the person, not the browser ────────────
def test_the_personal_order_is_kept_on_the_server(client, admin_id, guinea_id):
    """"הנשמר בין מכשיריו." A browser-local order would be a different strip
    on every machine somebody signs in from."""
    bid = _board(client, admin_id, invite=[guinea_id])
    a = _mk(client, bid, admin_id, "א").json()["id"]
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    _order(client, bid, guinea_id, [b, a])
    with Session(cityos_main.engine) as db:
        row = (db.query(BoardViewPrefs)
                 .filter(BoardViewPrefs.board_id == bid,
                         BoardViewPrefs.user_id == guinea_id).first())
    assert row is not None and row.order == [b, a]


# ── where a normal entry lands ─────────────────────────────────────────────
def test_the_first_entry_lands_on_the_main_table(client, admin_id):
    bid = _board(client, admin_id)
    _mk(client, bid, admin_id, "א")
    assert _strip(client, bid, admin_id)["last_view_id"] is None


def test_the_next_entry_lands_on_the_view_they_were_on(client, admin_id):
    bid = _board(client, admin_id)
    _mk(client, bid, admin_id, "א")
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    assert _last(client, bid, admin_id, b).status_code == 200
    assert _strip(client, bid, admin_id)["last_view_id"] == b


def test_it_is_each_persons_own(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    a = _mk(client, bid, admin_id, "א").json()["id"]
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    _last(client, bid, admin_id, a)
    _last(client, bid, guinea_id, b)
    assert _strip(client, bid, admin_id)["last_view_id"] == a
    assert _strip(client, bid, guinea_id)["last_view_id"] == b


def test_pinning_does_not_decide_where_anybody_lands(client, admin_id, guinea_id):
    """"הצמדה אינה קובעת תצוגת ברירת מחדל." Someone who has never opened a
    view still lands on the main table, with a pinned view at the top of the
    strip in front of them."""
    bid = _board(client, admin_id, invite=[guinea_id])
    a = _mk(client, bid, admin_id, "א").json()["id"]
    _patch(client, a, admin_id, pinned=True)
    strip = _strip(client, bid, guinea_id)
    assert strip["views"][0]["name"] == "א"
    assert strip["last_view_id"] is None, "a pin became somebody's default view"


def test_pinning_does_not_move_a_landing_place_already_chosen(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    a = _mk(client, bid, admin_id, "א").json()["id"]
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    _last(client, bid, guinea_id, b)
    _patch(client, a, admin_id, pinned=True)
    assert _strip(client, bid, guinea_id)["last_view_id"] == b


def test_a_landing_place_that_was_deleted_falls_back_to_the_main_table(client, admin_id):
    bid = _board(client, admin_id)
    a = _mk(client, bid, admin_id, "א").json()["id"]
    _last(client, bid, admin_id, a)
    client.delete(f"/api/views/{a}", headers=_h(admin_id))
    assert _strip(client, bid, admin_id)["last_view_id"] is None


def test_a_landing_place_that_became_unreadable_falls_back_too(client, admin_id, guinea_id):
    """The view is still there; its filter is no longer theirs to run. Opening
    it would be the block, every single entry."""
    bid = _board(client, admin_id, invite=[guinea_id])
    col = _column(client, bid, admin_id)
    v = _mk(client, bid, admin_id, "לפי תקציב", filters=_cut_on(col)).json()["id"]
    # both of them land there, and then only one of them loses the column
    assert _last(client, bid, guinea_id, v).json()["last_view_id"] == v
    assert _last(client, bid, admin_id, v).json()["last_view_id"] == v

    _deny(client, bid, admin_id, col, guinea_id)
    assert _strip(client, bid, guinea_id)["last_view_id"] is None
    assert _strip(client, bid, admin_id)["last_view_id"] == v, \
        "the fallback is about this reader, not about the view"


def test_a_view_they_cannot_open_is_not_recorded_as_where_they_were(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    col = _column(client, bid, admin_id)
    _deny(client, bid, admin_id, col, guinea_id)
    v = _mk(client, bid, admin_id, "לפי תקציב", filters=_cut_on(col)).json()["id"]
    assert _last(client, bid, guinea_id, v).json()["last_view_id"] is None


def test_a_view_from_another_board_is_not_recorded(client, admin_id):
    a = _board(client, admin_id, name="לוח א")
    b = _board(client, admin_id, name="לוח ב")
    elsewhere = _mk(client, b, admin_id, "שם").json()["id"]
    assert _last(client, a, admin_id, elsewhere).json()["last_view_id"] is None


def test_the_main_table_can_be_chosen_again(client, admin_id):
    bid = _board(client, admin_id)
    a = _mk(client, bid, admin_id, "א").json()["id"]
    _last(client, bid, admin_id, a)
    assert _last(client, bid, admin_id, None).json()["last_view_id"] is None
    assert _strip(client, bid, admin_id)["last_view_id"] is None


def test_recording_where_you_are_takes_only_the_right_to_look(client, admin_id, member_id):
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "viewer"})
    a = _mk(client, bid, admin_id, "א").json()["id"]
    assert _last(client, bid, member_id, a).status_code == 200


def test_it_is_not_a_way_into_a_board_you_cannot_open(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    a = _mk(client, bid, admin_id, "א").json()["id"]
    assert _last(client, bid, guinea_id, a).status_code == 403


# ── the address ────────────────────────────────────────────────────────────
def test_a_link_carries_both_the_board_and_the_view():
    """"קישור פנימי יכלול מזהי לוח ותצוגה ויחייב הרשאה." The permission half is
    the server's and is covered by the view listing's own gate; this is the
    address half."""
    src = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    i = src.index("const Router={")
    router = src[i:src.index("\n};", i)]
    assert "/board/" in router and "/view/" in router
    assert "viewId" in router
