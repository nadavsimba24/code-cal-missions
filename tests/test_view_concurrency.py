"""עריכות מקבילות, ולוג הניהול.

A shared tab has more than one person in front of it, so "save" cannot mean
"write what I have". Two of them adjust the same view, both press save, and
without a version the second one wins silently — the first person's work is
gone and nothing on either screen says so.

So a configuration save names the version it is overwriting. The version is
REQUIRED, which is the whole protection: a save that arrives without one is a
save that cannot be checked, and accepting it is exactly the silent overwrite
this exists to stop. "אין שמירה אוטומטית של גרסה מיושנת" — nor of an unstated
one, which is a stale version nobody bothered to name.

A stale save answers 409 rather than 403, because "you are behind" and "you
may not" are different facts and lead to different next actions: one is an
invitation to look again, the other is a refusal.

And the log records the management events — create, shared update, rename,
delete, restore, lock, pin — with who and when. A temporary adjustment is
explicitly not one of them, and could not be logged anyway: it never reaches
the server.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import AuditLog, SavedView  # noqa: E402

from test_saved_views import CUT, _board, _mk, _list, _cfg  # noqa: E402


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _version(vid):
    with Session(cityos_main.engine) as db:
        return db.query(SavedView).filter(SavedView.id == vid).one().config_version or 1


def _log(vid, action=None):
    with Session(cityos_main.engine) as db:
        q = db.query(AuditLog).filter(AuditLog.entity_type == "saved_view",
                                      AuditLog.entity_id == vid)
        if action:
            q = q.filter(AuditLog.action == action)
        return q.order_by(AuditLog.id).all()


def _raw(client, vid, uid, **body):
    return client.patch(f"/api/views/{vid}", json=dict(body, user_id=uid), headers=_h(uid))


# ── the version is required ────────────────────────────────────────────────
def test_a_configuration_save_without_a_version_is_refused(client, admin_id):
    """A save that cannot be checked is the silent overwrite itself."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    r = _raw(client, vid, admin_id, filters=dict(CUT, sort="due"))
    assert r.status_code == 400 and "גרסת התצורה" in r.json()["detail"]
    assert _version(vid) == 1, "it was saved anyway"


def test_a_save_naming_the_current_version_goes_through(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    assert _cfg(client, vid, admin_id, dict(CUT, sort="due")).status_code == 200
    assert _version(vid) == 2


def test_a_save_naming_an_older_version_is_refused(client, admin_id, guinea_id):
    """Two people on one tab. The second save does not win."""
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    both_saw = _version(vid)

    assert _raw(client, vid, admin_id, filters=dict(CUT, sort="due"),
                config_version=both_saw).status_code == 200
    r = _raw(client, vid, guinea_id, filters=dict(CUT, sort="title"),
             config_version=both_saw)
    assert r.status_code == 409, r.status_code

    with Session(cityos_main.engine) as db:
        assert db.query(SavedView).filter(SavedView.id == vid).one().filters["sort"] == "due", \
            "the stale save overwrote the one that was not"


def test_the_refusal_says_what_happened_and_what_the_version_is_now(client, admin_id):
    """The next thing that client does is reload and retry, so it is handed
    what it needs for both."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    _cfg(client, vid, admin_id, dict(CUT, sort="due"))
    r = _raw(client, vid, admin_id, filters=dict(CUT, sort="title"), config_version=1)
    body = r.json()["detail"]
    assert body["error"] == "stale_config"
    assert body["detail"] == "ההגדרות השתנו על ידי משתמש אחר"
    assert body["config_version"] == 2


def test_being_behind_is_not_the_same_answer_as_not_being_allowed(client, admin_id, guinea_id):
    """409 and 403 lead to different next actions: look again, or stop."""
    bid = _board(client, admin_id, invite=[guinea_id], role="viewer")
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    assert _raw(client, vid, guinea_id, filters=dict(CUT),
                config_version=1).status_code == 403


def test_a_version_that_is_not_a_number_is_refused(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    assert _raw(client, vid, admin_id, filters=dict(CUT),
                config_version="לא מספר").status_code == 400


def test_renaming_needs_no_version(client, admin_id):
    """A name is not a configuration, and the version does not move for it —
    so demanding one would be asking about something that cannot be stale."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    assert _raw(client, vid, admin_id, name="בשם אחר").status_code == 200


# ── the lock and the bin are checked when the action runs ──────────────────
def test_a_lock_applied_after_the_menu_opened_still_stops_the_save(client, admin_id, guinea_id):
    """"נעילה ומחיקה ייבדקו שוב בזמן הביצוע, ולא רק בעת פתיחת התפריט." The
    screen in front of them was drawn when it was unlocked."""
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    drawn = [v for v in _list(client, bid, guinea_id) if v["id"] == vid][0]
    assert drawn["can_edit"] is True                   # what their menu was built from

    _raw(client, vid, admin_id, locked=True)
    assert _cfg(client, vid, guinea_id, dict(CUT, sort="due")).status_code == 403
    assert _raw(client, vid, guinea_id, name="בשם אחר").status_code == 403
    assert client.delete(f"/api/views/{vid}", headers=_h(guinea_id)).status_code == 403


def test_a_view_deleted_after_the_menu_opened_cannot_be_saved_over(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    assert _raw(client, vid, guinea_id, filters=dict(CUT),
                config_version=1).status_code == 404


# ── the log ────────────────────────────────────────────────────────────────
def test_every_management_event_reaches_the_log(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    _cfg(client, vid, admin_id, dict(CUT, sort="due"))
    _raw(client, vid, admin_id, name="בשם אחר")
    _raw(client, vid, admin_id, locked=True)
    _raw(client, vid, admin_id, locked=False)
    _raw(client, vid, admin_id, pinned=True)
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    client.post(f"/api/views/{vid}/restore", json={"user_id": admin_id}, headers=_h(admin_id))

    actions = [r.action for r in _log(vid)]
    for want in ("create", "config", "rename", "lock", "unlock", "pin", "delete", "restore"):
        assert want in actions, (want, actions)


def test_each_line_says_who_and_when_and_what_changed(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "לפני").json()["id"]
    _raw(client, vid, admin_id, name="אחרי")
    row = _log(vid, "rename")[0]
    assert row.changed_by == admin_id
    assert row.created_at is not None
    assert row.old_value == "לפני" and row.new_value == "אחרי"


def test_the_log_does_not_carry_the_cut_itself(client, admin_id):
    """A cut can name a column somebody reading the log may not see, and a log
    is read by more people than a board."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    _cfg(client, vid, admin_id, dict(CUT, sort="due", priority="high"))
    row = _log(vid, "config")[0]
    blob = f"{row.old_value}|{row.new_value}|{row.field_name}"
    assert "high" not in blob and "adv" not in blob, blob
    assert row.new_value == "2", "the version is what a config event records"


def test_a_refused_save_writes_no_log_line(client, admin_id):
    """A log entry for a save that did not happen is worse than none."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    _cfg(client, vid, admin_id, dict(CUT, sort="due"))
    before = len(_log(vid))
    assert _raw(client, vid, admin_id, filters=dict(CUT), config_version=1).status_code == 409
    assert len(_log(vid)) == before


def test_a_temporary_adjustment_is_not_a_management_event(client, admin_id):
    """It never reaches the server, so there is nothing to log — and that is
    the rule rather than an accident of the implementation."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    before = len(_log(vid))
    client.post(f"/api/boards/{bid}/items/query",
                json={"user_id": admin_id, "q": "חיפוש זמני",
                      "today": "2026-10-20", "tz_offset": 180}, headers=_h(admin_id))
    assert len(_log(vid)) == before
