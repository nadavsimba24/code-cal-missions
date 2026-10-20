"""מחיקה ושחזור — חלון של 30 יום, ומה חוזר ומה לא.

Deleting a view hides it for everybody, so the restore is not a convenience:
it is the only thing standing between a misplaced click and a cut a department
built. It is kept for a window, and what comes back is deliberately not
everything that went in.

  the NAME comes back, with a suffix if it was taken meanwhile. Refusing the
    restore over a name would be refusing the thing somebody actually asked
    for; renaming what a person just typed would be a lie. The difference is
    who chose the name, which is why the two rules differ.

  the PIN does not. A pin puts the tab first for everyone, and people have
    arranged themselves around the strip as it is since. Coming back is the
    view's to ask for; the front of the strip is not.

  the LOCK does, with the configuration — both have to survive the window or
    the restore brings back something that is not what was deleted.

  a column that was deleted meanwhile does NOT come back, and the view says so
    instead of running without it. That is the one case where answering is
    worse than refusing: inside an "or" group, a rule that is gone shows the
    whole board with the filter apparently still on.
"""
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import AuditLog, SavedView  # noqa: E402

from test_saved_views import CUT, _board, _mk, _list  # noqa: E402
from test_view_column_permissions import _column, _cut_on  # noqa: E402


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _trash(client, bid, uid):
    r = client.get(f"/api/boards/{bid}/views/trash?user_id={uid}", headers=_h(uid))
    assert r.status_code == 200, r.text
    return r.json()["views"]


def _restore(client, vid, uid):
    return client.post(f"/api/views/{vid}/restore", json={"user_id": uid}, headers=_h(uid))


def _age(vid, days):
    """Move a deletion back in time, the only way to test a window."""
    with Session(cityos_main.engine) as db:
        v = db.query(SavedView).filter(SavedView.id == vid).first()
        v.deleted_at = datetime.now(timezone.utc) - timedelta(days=days)
        db.commit()


# ── the main table is not deletable ────────────────────────────────────────
def test_the_main_table_cannot_be_deleted(client, admin_id):
    """"לא ניתן למחוק את הטבלה הראשית."

    This case used to assert the opposite shape: that the main table had no
    row at all, which was the strongest form the rule could take while that
    was true. The record chapter made it a row — it needs an id to be linked
    to, a configuration version, and a place on the strip that is not a
    special case — so the rule is now enforced rather than structural, and
    that is exactly why it needs a case of its own."""
    bid = _board(client, admin_id)
    with Session(cityos_main.engine) as db:
        main = (db.query(SavedView)
                  .filter(SavedView.board_id == bid, SavedView.kind == "main").one())
        mid, name = main.id, main.name
    assert name == cityos_main.MAIN_VIEW_NAME

    r = client.delete(f"/api/views/{mid}", headers=_h(admin_id))
    assert r.status_code == 400 and "הטבלה הראשית" in r.json()["detail"]
    with Session(cityos_main.engine) as db:
        assert db.query(SavedView).filter(SavedView.id == mid).one().deleted_at is None


# ── the window ─────────────────────────────────────────────────────────────
def test_a_view_can_be_restored_inside_the_window(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "זמנית").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    _age(vid, cityos_main.VIEW_RESTORE_DAYS - 1)
    assert _restore(client, vid, admin_id).status_code == 200
    assert [v["name"] for v in _list(client, bid, admin_id)] == ["זמנית"]


def test_and_not_after_it(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "זמנית").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    _age(vid, cityos_main.VIEW_RESTORE_DAYS + 1)
    r = _restore(client, vid, admin_id)
    assert r.status_code == 400 and str(cityos_main.VIEW_RESTORE_DAYS) in r.json()["detail"]


def test_the_log_stops_offering_what_it_can_no_longer_do(client, admin_id):
    """An offer that fails when pressed is worse than no offer."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "זמנית").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    assert len(_trash(client, bid, admin_id)) == 1
    _age(vid, cityos_main.VIEW_RESTORE_DAYS + 1)
    assert _trash(client, bid, admin_id) == []


def test_the_row_is_not_erased_when_the_window_closes(client, admin_id):
    """A window on restoring, not a promise to destroy data on a timer."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "זמנית").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    _age(vid, cityos_main.VIEW_RESTORE_DAYS + 5)
    with Session(cityos_main.engine) as db:
        assert db.query(SavedView).filter(SavedView.id == vid).first() is not None


def test_the_window_is_configurable():
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ.get("VIEW_RESTORE_DAYS"' in src
    assert cityos_main.VIEW_RESTORE_DAYS == 30


# ── what the deletion leaves in the board's log ────────────────────────────
def test_the_deletion_is_recorded_where_the_restore_is_offered(client, admin_id):
    """"בעל הלוח יוכל לשחזר דרך לוג הלוח" — so the log has to carry it."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "זמנית").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    with Session(cityos_main.engine) as db:
        row = (db.query(AuditLog)
                 .filter(AuditLog.entity_type == "saved_view", AuditLog.entity_id == vid,
                         AuditLog.action == "delete").first())
    assert row is not None
    assert row.old_value == "זמנית", "the log does not say which view went"
    assert row.changed_by == admin_id


def test_the_restore_is_recorded_too(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "זמנית").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    _restore(client, vid, admin_id)
    with Session(cityos_main.engine) as db:
        assert db.query(AuditLog).filter(AuditLog.entity_type == "saved_view",
                                         AuditLog.entity_id == vid,
                                         AuditLog.action == "restore").count() == 1


# ── what survives, and what does not ───────────────────────────────────────
def test_the_configuration_and_the_lock_survive_the_window(client, admin_id):
    bid = _board(client, admin_id)
    cols = {"order": ["item", "status"], "hidden": ["due"], "widths": {"item": 321}}
    vid = _mk(client, bid, admin_id, "נעולה", filters=dict(CUT, cols=cols)).json()["id"]
    client.patch(f"/api/views/{vid}", json={"user_id": admin_id, "locked": True},
                 headers=_h(admin_id))
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    _age(vid, cityos_main.VIEW_RESTORE_DAYS - 1)

    r = _restore(client, vid, admin_id)
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is True, "the lock did not survive"
    back = [v for v in _list(client, bid, admin_id) if v["id"] == vid][0]
    assert back["filters"]["cols"] == cols


def test_the_pin_is_not_restored(client, admin_id):
    """"ההצמדה לא תשוחזר אוטומטית, כדי לא לשנות את סדר הניווט הקיים."" """
    bid = _board(client, admin_id)
    first = _mk(client, bid, admin_id, "שגרתית").json()["id"]
    vid = _mk(client, bid, admin_id, "מוצמדת").json()["id"]
    client.patch(f"/api/views/{vid}", json={"user_id": admin_id, "pinned": True},
                 headers=_h(admin_id))
    assert [v["name"] for v in _list(client, bid, admin_id)][0] == "מוצמדת"

    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    r = _restore(client, vid, admin_id)
    assert r.status_code == 200, r.text
    assert r.json()["pinned"] is False
    assert [v["name"] for v in _list(client, bid, admin_id)][0] == "שגרתית", \
        "the restore pushed itself back to the front of everybody's strip"
    assert first


# ── a column that went missing while the view was away ─────────────────────
@pytest.fixture
def orphaned(client, admin_id):
    """A view filtering on a column, and then the column is deleted."""
    bid = _board(client, admin_id)
    col = _column(client, bid, admin_id)
    vid = _mk(client, bid, admin_id, "לפי תקציב", filters=_cut_on(col)).json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    r = client.patch(f"/api/boards/{bid}", json={"columns": [], "user_id": admin_id},
                     headers=_h(admin_id))
    assert r.status_code == 200, r.text
    return {"bid": bid, "vid": vid, "col": col, "owner": admin_id}


def test_a_view_whose_column_went_comes_back_needing_a_fix(client, orphaned):
    r = _restore(client, orphaned["vid"], orphaned["owner"])
    assert r.status_code == 200, r.text
    assert r.json()["needs_fix"] == [orphaned["col"]]

    on_strip = [v for v in _list(client, orphaned["bid"], orphaned["owner"])
                if v["id"] == orphaned["vid"]][0]
    assert on_strip["needs_fix"] == [orphaned["col"]]


def test_and_it_does_not_answer_with_partial_results(client, orphaned):
    """The misleading half: dropping the dead rule and running the rest shows
    the whole board inside an "or" group, filter apparently still on."""
    _restore(client, orphaned["vid"], orphaned["owner"])
    r = client.post(f"/api/boards/{orphaned['bid']}/items/query",
                    # `filter` is the key the query endpoint reads — a view
                    # stores the tree as `adv` and the client sends it under
                    # this name. Posting `adv` here sent no tree at all, and
                    # the case passed on a whole-board answer, which is the
                    # very thing it exists to refuse.
                    json={"user_id": orphaned["owner"], "view_id": orphaned["vid"],
                          "filter": _cut_on(orphaned["col"])["adv"],
                          "today": "2026-10-20", "tz_offset": 180},
                    headers=_h(orphaned["owner"]))
    assert r.status_code == 409, r.text
    assert "נמחקה" in r.json()["detail"]


def test_a_healthy_view_says_it_needs_nothing(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "בריאה").json()["id"]
    v = [x for x in _list(client, bid, admin_id) if x["id"] == vid][0]
    assert v["needs_fix"] == []
