"""פעולות שרת ובקרת הרשאות — מה חייב להיות אטומי, ומה נבדק מחדש בכל בקשה.

The operations themselves existed before this chapter; what it asks for is
that two of their guarantees be real rather than usually real.

ATOMIC. "בדיקות שם ייחודי ומגבלת תצוגות ייאכפו באופן אטומי." Both are
read-then-write races. _check_view_name reads, the insert writes, and between
those two the answer can change — two people naming a view the same thing at
the same moment both pass and both land. The check stays, because it is what
produces a sentence somebody can act on; underneath it the database refuses
the second write through a partial unique index, and the refusal is translated
back into the same 400. The ceiling cannot be an index, so it is re-counted
inside the transaction and rolled back if the row that just landed put the
board over.

RE-CHECKED. "חוסר הרשאה ייחסם גם בבקשה ישירה, גם לאחר שינוי הרשאות במהלך
ביקור וגם בשימוש בקישור ישן." All three are the same rule seen from three
angles: the answer is computed from the request in front of the server, never
from what was true when a screen was drawn or a link was copied.
"""
import pathlib
import re
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import SavedView  # noqa: E402

from test_saved_views import CUT, _board, _mk, _list  # noqa: E402


def _h(uid):
    return {"X-CityOS-User": str(uid)}


# ── the uniqueness rule has a floor under it ───────────────────────────────
def test_the_database_itself_refuses_a_duplicate_name(client, admin_id):
    """The check can be bypassed — by a race, or by any future caller that
    forgets it. The index cannot."""
    bid = _board(client, admin_id)
    _mk(client, bid, admin_id, "דחופים")
    with Session(cityos_main.engine) as db:
        db.add(SavedView(board_id=bid, owner_id=admin_id, name="דחופים",
                         visibility="public", filters={}))
        with pytest.raises(Exception) as e:
            db.commit()
        assert "ux_saved_views_board_name" in str(e.value) or "unique" in str(e.value).lower()


@pytest.mark.parametrize("second", ["דחופים", "  דחופים  ", "DCHUFIM"])
def test_the_index_compares_the_way_the_rule_does(client, admin_id, second):
    """Trimmed and without case, so the floor cannot be lower than the rule
    it is holding up."""
    bid = _board(client, admin_id)
    first = "DCHUFIM" if second == "DCHUFIM" else "דחופים"
    _mk(client, bid, admin_id, first)
    with Session(cityos_main.engine) as db:
        db.add(SavedView(board_id=bid, owner_id=admin_id, name=second,
                         visibility="public", filters={}))
        with pytest.raises(Exception):
            db.commit()


def test_a_name_in_the_bin_does_not_hold_the_floor_either(client, admin_id):
    """Live rows only — the restore depends on it, and so does reusing a name
    somebody freed."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "דחופים").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    assert _mk(client, bid, admin_id, "דחופים").status_code == 200


def test_a_constraint_violation_reads_like_the_check(client, admin_id, monkeypatch):
    """Somebody who hits the FLOOR instead of the check must not get a
    different sentence — or a 500.

    Reached by disabling the check, which is the only way to get there on
    purpose: in ordinary use the check answers first, and a race is not a
    thing a test can schedule. Without this the translation was never
    exercised at all — removing it broke nothing, which is how an unreachable
    except clause becomes a 500 in front of a real user one day."""
    bid = _board(client, admin_id)
    _mk(client, bid, admin_id, "דחופים")

    monkeypatch.setattr(cityos_main, "_check_view_name",
                        lambda db, board_id, name, exclude_id=None: (name or "").strip())
    r = _mk(client, bid, admin_id, "  דחופים  ")
    assert r.status_code == 400, r.status_code
    assert "כבר יש תצוגה בשם הזה" in r.json()["detail"]


def test_the_ceiling_is_rechecked_inside_the_transaction():
    """It cannot be an index, so it is counted after the row lands and rolled
    back if that put the board over."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    m = re.search(r"def _commit_view\(.*?\n\n\n", src, re.S)
    assert m, "_commit_view moved"
    body = m.group(0)
    assert "db.flush()" in body and "db.rollback()" in body
    assert "IntegrityError" in body, "a duplicate name would surface as a 500"


def test_a_board_is_never_lost_to_its_own_bookkeeping(client, admin_id):
    """The main row is written after the board's own commit and can never
    fail it. A board that could not be created because its main table
    collided with something would be a board lost to bookkeeping — and the
    row is recoverable by the backfill, while the board is not."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    i = src.index("def create_board(")
    body = src[i:src.index("\n# ── Import a board", i)]
    add = body.index('kind="main"')
    assert body.count("db.commit()", 0, add) >= 1, "the board is not committed first"
    assert "except IntegrityError" in body[add:], "the main row can still fail the board"
    # and it really does produce a board, with its table
    bid = _board(client, admin_id)
    with Session(cityos_main.engine) as db:
        assert db.query(SavedView).filter(SavedView.board_id == bid,
                                          SavedView.kind == "main").count() == 1


# ── permission is answered from the request in front of the server ─────────
def test_a_direct_request_is_refused_without_the_screen(client, admin_id, guinea_id):
    """No screen was drawn, no flag was read — the endpoint answers for
    itself."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "שלי").json()["id"]
    for call in (
        lambda: client.patch(f"/api/views/{vid}", json={"user_id": guinea_id, "name": "לא"},
                             headers=_h(guinea_id)),
        lambda: client.delete(f"/api/views/{vid}", headers=_h(guinea_id)),
        lambda: client.post(f"/api/views/{vid}/duplicate", json={"user_id": guinea_id},
                            headers=_h(guinea_id)),
        lambda: client.post(f"/api/views/{vid}/restore", json={"user_id": guinea_id},
                            headers=_h(guinea_id)),
    ):
        assert call().status_code == 403


def test_a_permission_taken_away_mid_visit_takes_effect_on_the_next_request(client, admin_id, guinea_id):
    """"גם לאחר שינוי הרשאות במהלך ביקור." The screen in front of them still
    says editor; the server does not care what it says."""
    bid = _board(client, admin_id, invite=[guinea_id], role="editor")
    vid = _mk(client, bid, admin_id, "שלי").json()["id"]
    assert client.patch(f"/api/views/{vid}", json={"user_id": guinea_id, "name": "בשם אחר"},
                        headers=_h(guinea_id)).status_code == 200

    r = client.patch(f"/api/boards/{bid}/members/{guinea_id}",
                     json={"actor_id": admin_id, "role": "viewer"}, headers=_h(admin_id))
    assert r.status_code == 200, r.text
    assert client.patch(f"/api/views/{vid}", json={"user_id": guinea_id, "name": "ושוב"},
                        headers=_h(guinea_id)).status_code == 403


def test_removal_from_the_board_takes_the_views_with_it(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    _mk(client, bid, admin_id, "שלי")
    assert len(_list(client, bid, guinea_id)) == 1

    r = client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}",
                      headers=_h(admin_id))
    assert r.status_code == 200, r.text
    assert client.get(f"/api/boards/{bid}/views?user_id={guinea_id}",
                      headers=_h(guinea_id)).status_code == 403


def test_an_old_link_is_answered_now_and_not_when_it_was_made(client, admin_id, guinea_id):
    """"וגם בשימוש בקישור ישן." The id in somebody's address bar is a
    question, not a permission."""
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, admin_id, "שלי").json()["id"]
    assert [v for v in _list(client, bid, guinea_id) if v["id"] == vid]

    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}",
                  headers=_h(admin_id))
    # the same link, a moment later
    assert client.get(f"/api/boards/{bid}/views?user_id={guinea_id}",
                      headers=_h(guinea_id)).status_code == 403
    assert client.patch(f"/api/views/{vid}", json={"user_id": guinea_id, "name": "x"},
                        headers=_h(guinea_id)).status_code == 403


def test_a_link_to_a_view_on_another_board_is_not_a_way_in(client, admin_id):
    """"יוודא שכל מזהי הלוח ... שייכים להקשר המתאים." A view id that is real
    but belongs somewhere else must not be answered for here."""
    a = _board(client, admin_id, name="לוח א")
    b = _board(client, admin_id, name="לוח ב")
    elsewhere = _mk(client, b, admin_id, "שם").json()["id"]
    r = client.put(f"/api/boards/{a}/views/order",
                   json={"user_id": admin_id, "order": [elsewhere]}, headers=_h(admin_id))
    assert r.json()["order"] == [], "a view from another board was arranged into this one"
