"""רשומות נדרשות — מה שורת תצוגה מחזיקה, ומה נשמר בנפרד לאדם.

The fields are a list in the spec, and most of them were already there. Three
were not, and each is here because of something that could not be done without
it:

  kind — the board's fixed table used to be nothing at all: the board itself,
    its layout in board.settings and no record to point at. It could not be
    named in a link the way a saved view can, could not carry a configuration
    version, and had to be special-cased in every place that lists views —
    which is how "the main table's name is taken" came to be a hardcoded
    string rather than a row like every other name on the strip.

  config_version — a counter, not a timestamp. Two saves in one clock tick
    compare equal, and a client deciding whether what it holds is stale cannot
    afford "nearly". It also says how many times the configuration moved,
    which a timestamp cannot.

  schema_version — nothing reads it, which is the point. It is here so that
    the day the shape of `filters` changes, the rows written before that day
    can SAY so instead of being guessed at by their contents.

And one rule about a field that was already there: the creator is documentation
and nothing else — "היוצר משמש לתיעוד ואינו מכתיב הרשאות ניהול".
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import Board, BoardViewPrefs, SavedView  # noqa: E402

from test_saved_views import CUT, _board, _mk, _list, _cfg  # noqa: E402


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _main_of(bid):
    with Session(cityos_main.engine) as db:
        return (db.query(SavedView)
                  .filter(SavedView.board_id == bid, SavedView.kind == "main").one())


def _row(bid, vid):
    with Session(cityos_main.engine) as db:
        return db.query(SavedView).filter(SavedView.id == vid).one()


# ── every field the record is required to carry ────────────────────────────
REQUIRED = {"id", "board_id", "kind", "name", "owner_id", "filters", "position",
            "locked", "pinned", "config_version", "schema_version",
            "created_at", "updated_at", "deleted_at", "deleted_by"}


def test_the_record_carries_every_required_field():
    have = {c.name for c in SavedView.__table__.columns}
    missing = REQUIRED - have
    assert not missing, missing


# ── a board starts with no tabs at all ─────────────────────────────────────
def test_a_new_board_has_no_view_tabs(client, admin_id):
    """There was briefly a row per board called "טבלה ראשית", created
    automatically so the board's fixed table had an id to be linked to. It
    meant every board grew a tab nobody asked for.

    A tab is something somebody added. A board with none shows none, and the
    board's own table is what it always was: the board."""
    bid = _board(client, admin_id)
    with Session(cityos_main.engine) as db:
        assert db.query(SavedView).filter(SavedView.board_id == bid).count() == 0
    assert _list(client, bid, admin_id, main=True) == []


def test_the_first_view_somebody_adds_is_called_tavla(client, admin_id):
    bid = _board(client, admin_id)
    r = client.post(f"/api/boards/{bid}/views",
                    json={"user_id": admin_id, "filters": {"view": "table"}},
                    headers=_h(admin_id))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "טבלה"
    assert [v["name"] for v in _list(client, bid, admin_id, main=True)] == ["טבלה"]


def test_nothing_writes_the_main_kind_any_more(client, admin_id):
    """The `kind` column stays on the model for the day a fixed table needs a
    record again. Nothing produces one now, and this is what says so."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'kind="main"' not in src, "something still creates a main-table row"
    assert "_ensure_main_views" not in src, "the backfill is still there"


# ── the configuration version ──────────────────────────────────────────────
def test_a_new_view_starts_at_version_one(client, admin_id):
    bid = _board(client, admin_id)
    v = _mk(client, bid, admin_id, "חדשה").json()
    assert v["config_version"] == 1 and v["schema_version"] == 1


def test_saving_the_configuration_moves_the_version(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "חדשה").json()["id"]
    for n in (2, 3):
        _cfg(client, vid, admin_id, dict(CUT, sort="due"))
        assert _row(bid, vid).config_version == n


def test_renaming_does_not_move_the_configuration_version(client, admin_id):
    """A name is not a configuration. Bumping on a rename would tell every
    client holding the view that what it has is stale when nothing it holds
    has changed."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "חדשה").json()["id"]
    before = _row(bid, vid).config_version
    client.patch(f"/api/views/{vid}", json={"user_id": admin_id, "name": "בשם אחר"},
                 headers=_h(admin_id))
    assert _row(bid, vid).config_version == before


def test_locking_and_pinning_do_not_move_it_either(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "חדשה").json()["id"]
    before = _row(bid, vid).config_version
    for body in ({"locked": True}, {"locked": False}, {"pinned": True}):
        client.patch(f"/api/views/{vid}", json=dict(body, user_id=admin_id),
                     headers=_h(admin_id))
    assert _row(bid, vid).config_version == before


def test_the_version_travels_to_the_client(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "חדשה").json()["id"]
    _cfg(client, vid, admin_id, dict(CUT, sort="due"))
    v = [x for x in _list(client, bid, admin_id) if x["id"] == vid][0]
    assert v["config_version"] == 2


# ── the creator documents, it does not govern ──────────────────────────────
def test_the_creator_does_not_decide_who_may_manage_the_view(client, admin_id, guinea_id, member_id):
    """"היוצר משמש לתיעוד ואינו מכתיב הרשאות ניהול." Two editors, one of whom
    made the view: both may change it, and the one who made it gets nothing
    extra."""
    bid = _board(client, admin_id, invite=[guinea_id, member_id])
    vid = _mk(client, bid, guinea_id, "של דנה").json()["id"]
    assert _row(bid, vid).owner_id == guinea_id, "the record does not say who made it"

    for uid in (guinea_id, member_id):
        r = client.patch(f"/api/views/{vid}", json={"user_id": uid, "name": f"שם {uid}"},
                         headers=_h(uid))
        assert r.status_code == 200, (uid, r.text)


def test_and_gets_nothing_extra_once_it_is_locked(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, guinea_id, "שלי").json()["id"]
    client.patch(f"/api/views/{vid}", json={"user_id": admin_id, "locked": True},
                 headers=_h(admin_id))
    r = client.patch(f"/api/views/{vid}", json={"user_id": guinea_id, "name": "בכל זאת"},
                     headers=_h(guinea_id))
    assert r.status_code == 403


# ── what is kept per person, and what is not kept at all ───────────────────
def test_the_personal_preferences_are_two_and_live_apart(client, admin_id):
    """"אלה נשמרים בנפרד מהתצורה המשותפת" — a different table, not a corner
    of the view's own row."""
    cols = {c.name for c in BoardViewPrefs.__table__.columns}
    assert cols == {"id", "board_id", "user_id", "order", "last_view_id", "updated_at"}
    shared = {c.name for c in SavedView.__table__.columns}
    assert "last_view_id" not in shared and "order" not in shared
