"""שמירה לכולם — מה הכפתור הזה שומר, למי הוא מוצע, ומה קורה כשהוא נכשל.

A change to a view's settings is somebody's own until they press this. The
chapter is mostly about the screen, but three of its sentences are promises
only the server can keep:

  "שומרת את כל רכיבי התצורה הנתמכים יחד" — one write, not one per component.
    Half a saved layout is worse than none: the columns move and the widths do
    not, and nobody can tell whether that was the save or the author.

  "בכישלון, התצורה המשותפת לא תשתנה" — a refusal anywhere in the request
    leaves the stored row exactly as it was, including the parts that were
    fine. The screen keeps the adjustments so they can be tried again, which
    only works if the server did not take half of them.

  "לעורך בטבלה הראשית או בתצוגה נעולה תוצע רק שמירה כתצוגה חדשה" — the offer
    is drawn from can_edit, and the server has to refuse the write itself
    regardless of what the screen drew.

And one it half keeps: a reader with no local adjustments should get the new
configuration without reloading. The server's share of that is the doorbell
and a version to compare — see view.changed and updated_at.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import SavedView  # noqa: E402

from test_saved_views import CUT, _board, _mk, _list  # noqa: E402
from test_view_column_permissions import _column, _cut_on, _deny  # noqa: E402


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _save(client, vid, uid, **body):
    return client.patch(f"/api/views/{vid}", json=dict(body, user_id=uid), headers=_h(uid))


def _stored(vid):
    with Session(cityos_main.engine) as db:
        v = db.query(SavedView).filter(SavedView.id == vid).first()
        return {"name": v.name, "filters": v.filters, "locked": v.locked}


WHOLE = {"cols": {"order": ["item", "status"], "hidden": ["due"], "widths": {"item": 300}},
         "adv": {"op": "and", "rules": [{"field": "status", "op": "ne", "v": "done"}]},
         "sort": "due:asc", "priority": "high"}


# ── all of it, in one go ───────────────────────────────────────────────────
def test_every_component_lands_in_one_write(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    assert _save(client, vid, admin_id, filters=dict(WHOLE)).status_code == 200
    got = _stored(vid)["filters"]
    assert got["cols"] == WHOLE["cols"] and got["adv"] == WHOLE["adv"]
    assert got["sort"] == WHOLE["sort"] and got["priority"] == WHOLE["priority"]


def test_the_search_text_is_not_part_of_it(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    _save(client, vid, admin_id, filters=dict(WHOLE, q="מה שחיפשתי"))
    assert "q" not in _stored(vid)["filters"]
    assert _stored(vid)["filters"]["cols"] == WHOLE["cols"], "the rest went with it"


# ── a refusal changes nothing ──────────────────────────────────────────────
def test_a_refused_save_leaves_the_shared_configuration_alone(client, admin_id):
    """The name is read before the filters are. A request carrying a good name
    and a filter that is refused must not land the name — the screen is about
    to offer the whole thing again."""
    bid = _board(client, admin_id)
    _mk(client, bid, admin_id, "תפוס")
    vid = _mk(client, bid, admin_id, "תצוגה", filters=dict(WHOLE)).json()["id"]
    before = _stored(vid)

    r = _save(client, vid, admin_id, name="בשם אחר",
              filters=dict(WHOLE, adv={"op": "and", "rules": [
                  {"field": "status", "op": "DROP"}]}))
    assert r.status_code == 400, r.text
    assert _stored(vid) == before, "a refused save left part of itself behind"


def test_a_refused_name_does_not_land_the_filters(client, admin_id):
    """The other order, for the same reason."""
    bid = _board(client, admin_id)
    _mk(client, bid, admin_id, "תפוס")
    vid = _mk(client, bid, admin_id, "תצוגה", filters=dict(WHOLE)).json()["id"]
    before = _stored(vid)

    r = _save(client, vid, admin_id, name="תפוס",
              filters=dict(WHOLE, sort="title:desc"))
    assert r.status_code == 400
    assert _stored(vid) == before


def test_a_save_refused_on_a_column_changes_nothing(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    col = _column(client, bid, admin_id)
    vid = _mk(client, bid, admin_id, "לפי תקציב", filters=_cut_on(col)).json()["id"]
    _deny(client, bid, admin_id, col, guinea_id)
    before = _stored(vid)

    r = _save(client, vid, guinea_id, name="שלי", filters=dict(WHOLE))
    assert r.status_code == 403
    assert _stored(vid) == before


# ── who is offered the save ────────────────────────────────────────────────
def test_an_editor_is_not_offered_the_save_on_a_locked_view(client, admin_id, guinea_id):
    """"לעורך ... בתצוגה נעולה תוצע רק שמירה כתצוגה חדשה." The offer is
    can_edit; the refusal is the server's own, whatever the screen drew."""
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, admin_id, "נעולה", filters=dict(WHOLE)).json()["id"]
    _save(client, vid, admin_id, locked=True)

    theirs = [v for v in _list(client, bid, guinea_id) if v["id"] == vid][0]
    assert theirs["can_edit"] is False
    before = _stored(vid)
    assert _save(client, vid, guinea_id, filters=dict(WHOLE, sort="x")).status_code == 403
    assert _stored(vid) == before
    # and the alternative actually works for them
    assert _mk(client, bid, guinea_id, "הגרסה שלי", filters=dict(WHOLE)).status_code == 200


def test_an_editor_cannot_save_the_main_tables_configuration_for_everyone(client, admin_id, guinea_id):
    """The main table is the board, so saving its layout for everyone is a
    change to the board — "שמירת תצורה לכולם בטבלה הראשית: בעל לוח כן, עורך
    לא". Their route is a new view of their own."""
    bid = _board(client, admin_id, invite=[guinea_id])
    for field in ("col_widths", "col_order", "col_hidden"):
        payload = {"actor_id": guinea_id, field: {"item": 300} if field == "col_widths" else []}
        r = client.patch(f"/api/boards/{bid}", json=payload, headers=_h(guinea_id))
        assert r.status_code == 403, f"{field}: {r.text}"
    assert _mk(client, bid, guinea_id, "הגרסה שלי", filters=dict(WHOLE)).status_code == 200


# ── telling everybody else ─────────────────────────────────────────────────
def test_the_strip_says_when_the_shared_configuration_last_changed(client, admin_id):
    """A reader holding temporary adjustments compares this with what they
    opened, and says so instead of discarding what they were doing."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    first = [v for v in _list(client, bid, admin_id) if v["id"] == vid][0]["updated_at"]
    assert first

    _save(client, vid, admin_id, filters=dict(WHOLE))
    later = [v for v in _list(client, bid, admin_id) if v["id"] == vid][0]["updated_at"]
    assert later and later > first, "a save did not move the version"


def test_a_save_rings_the_doorbell(client, admin_id, monkeypatch):
    """"בלי לטעון מחדש את הלוח" — the server publishes, the client decides.
    Deliberately the event and not the configuration: only the client knows
    whether this reader has adjustments to protect."""
    seen = []
    monkeypatch.setattr(cityos_main.bus, "publish",
                        lambda t, **kw: seen.append((t, kw)))
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    _save(client, vid, admin_id, filters=dict(WHOLE))

    rung = [kw for t, kw in seen if t == "view.changed"]
    assert rung, [t for t, _ in seen]
    assert rung[-1]["board_id"] == bid and rung[-1]["view_id"] == vid
    assert rung[-1]["actor_id"] == admin_id, "the saver cannot be told apart from everyone else"
