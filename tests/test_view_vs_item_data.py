"""הפרדה מעריכת נתוני פריט — שמירת תצוגה אינה נוגעת בנתונים, ולהפך.

Two things happen on the same screen and must not be confused for each other.
Adjusting a view is somebody's own until they save it for everyone, and it
resets when they leave. Editing a cell is a change to the board, saved by the
board's own process, and leaving the view does not undo it.

The confusion would be expensive in both directions: an item edit treated as a
temporary view adjustment is work somebody loses by clicking another tab, and
a view save that wrote item data is a layout change that quietly edited the
board.

And one consequence worth building for: an edit can push the row out of the
cut it was made in. The row goes, and the person who just typed into it is
told where it went — which means the server has to be able to answer "does
this item still match", exactly, for one named row.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import SavedView, Task  # noqa: E402

from test_saved_views import CUT, _board, _mk, _list, _cfg  # noqa: E402


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


def _snapshot(bid):
    with Session(cityos_main.engine) as db:
        return {t.id: (t.title, t.status, t.priority, t.custom_fields)
                for t in db.query(Task).filter(Task.board_id == bid).all()}


OPEN_ONLY = {"op": "and", "rules": [{"field": "status", "op": "ne", "v": "done"}]}


# ── saving a view touches no data ──────────────────────────────────────────
def test_saving_a_view_for_everyone_changes_no_item(client, admin_id):
    bid = _board(client, admin_id)
    _item(client, bid, admin_id, "פריט")
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    before = _snapshot(bid)

    r = _cfg(client, vid, admin_id, dict(CUT, cols={"widths": {"item": 400}}, sort="due:asc"))
    assert r.status_code == 200, r.text
    assert _snapshot(bid) == before, "a view save wrote item data"


def test_nor_does_creating_or_copying_or_deleting_one(client, admin_id):
    bid = _board(client, admin_id)
    _item(client, bid, admin_id, "פריט")
    before = _snapshot(bid)

    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id}, headers=_h(admin_id))
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    client.post(f"/api/views/{vid}/restore", json={"user_id": admin_id}, headers=_h(admin_id))
    assert _snapshot(bid) == before


# ── editing data does not touch the view, and survives leaving it ──────────
def test_editing_an_item_changes_no_view(client, admin_id):
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id, "פריט")
    vid = _mk(client, bid, admin_id, "תצוגה", filters=dict(CUT)).json()["id"]
    with Session(cityos_main.engine) as db:
        before = dict(db.query(SavedView).filter(SavedView.id == vid).first().filters)

    r = client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "title": "שם חדש"},
                     headers=_h(admin_id))
    assert r.status_code == 200, r.text
    with Session(cityos_main.engine) as db:
        assert dict(db.query(SavedView).filter(SavedView.id == vid).first().filters) == before


def test_an_edit_outlives_the_view_it_was_made_in(client, admin_id):
    """"אינם מתאפסים ביציאה מהתצוגה." The edit belongs to the board; the view
    was only where somebody happened to be standing."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id, "פריט")
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "title": "שם חדש"},
                 headers=_h(admin_id))

    client.delete(f"/api/views/{vid}", headers=_h(admin_id))     # the view goes entirely
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.id == tid).first().title == "שם חדש"


# ── the row that falls out of the cut ──────────────────────────────────────
def test_an_item_can_be_asked_about_by_name(client, admin_id):
    """A page of matches cannot answer "did THIS row fall out": an id absent
    from the first fifty has either stopped matching or just sits lower down.
    Asked about by name, the answer is exact whatever the board's size."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id, "פריט")
    r = _query(client, bid, admin_id, filter=OPEN_ONLY, only=[tid]).json()
    assert r["item_ids"] == [tid] and r["asked"] == [tid]


def test_an_edit_that_pushes_it_out_of_the_cut_says_so(client, admin_id):
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id, "פריט")
    assert _query(client, bid, admin_id, filter=OPEN_ONLY, only=[tid]).json()["item_ids"] == [tid]

    r = client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "status": "done"},
                     headers=_h(admin_id))
    assert r.status_code == 200, r.text
    after = _query(client, bid, admin_id, filter=OPEN_ONLY, only=[tid]).json()
    assert after["item_ids"] == [], "the row still answers the cut it left"
    assert after["asked"] == [tid], "the caller cannot tell which row was answered for"


def test_asking_about_one_row_does_not_return_the_others(client, admin_id):
    bid = _board(client, admin_id)
    a = _item(client, bid, admin_id, "א")
    _item(client, bid, admin_id, "ב")
    r = _query(client, bid, admin_id, filter=OPEN_ONLY, only=[a]).json()
    assert r["item_ids"] == [a]
    assert "items" not in r, "a question about one row was answered with a page"


def test_the_question_is_asked_under_the_same_permissions(client, admin_id, guinea_id):
    """It is the same question about one row, so it cannot be a way round the
    rules the general one obeys."""
    bid = _board(client, admin_id, invite=[guinea_id])
    hidden = _item(client, bid, admin_id, "חסוי")
    client.post(f"/api/tasks/{hidden}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"},
                headers=_h(admin_id))
    r = _query(client, bid, guinea_id, filter=OPEN_ONLY, only=[hidden]).json()
    assert r["item_ids"] == []


def test_asking_about_a_row_on_another_board_answers_nothing(client, admin_id):
    a = _board(client, admin_id, name="לוח א")
    b = _board(client, admin_id, name="לוח ב")
    elsewhere = _item(client, b, admin_id, "שם")
    r = _query(client, a, admin_id, filter=OPEN_ONLY, only=[elsewhere]).json()
    assert r["item_ids"] == []
