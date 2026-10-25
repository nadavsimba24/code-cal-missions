"""שמירת תצורה והתאמות זמניות — מה נשמר לכולם, ומה נשאר אצל מי שעשה אותו.

The spec gives this as a table, and the table has two columns. The left one is
a saved view: visible columns and their order, column widths, filters, sort.
The right one is everything a person does to a board while they are looking at
it — searching, collapsing a group, scrolling, opening a sub-item — which
belongs to them for as long as they are there.

The line between them is enforced as a list of what is KEPT, not a list of
what is stripped, and the two fail in opposite directions. A strip-list lets
anything new the client starts sending ride along into everybody's tab, and
the first anybody knows of it is a view that behaves differently for the
person who saved it. A keep-list turns that into a decision somebody has to
make on purpose, in one place, with this file failing until they do.

The last row of the table — the personal order of unpinned views — is not here
because it is not part of a view at all: it is kept per person, and
tests/test_view_navigation.py owns it.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import SavedView  # noqa: E402

from test_saved_views import CUT, _board, _mk, _list, _cfg  # noqa: E402


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _stored(vid):
    with Session(cityos_main.engine) as db:
        return db.query(SavedView).filter(SavedView.id == vid).first().filters


# ── the left-hand column: what a view is ───────────────────────────────────
SHARED = {
    "cols": {"order": ["item", "status"], "hidden": ["due"], "widths": {"item": 300}},
    "adv": {"op": "and", "rules": [{"field": "status", "op": "ne", "v": "done"}]},
    "sort": "due:asc",
    "priority": "high",
    "people": [],
    "status": "",
    "links": {"col": "", "mode": "", "item": 0},
    "view": "table",
}


@pytest.mark.parametrize("key", sorted(SHARED))
def test_every_shared_component_survives_a_save(client, admin_id, key):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, f"עם {key}", filters=dict(SHARED)).json()["id"]
    assert _stored(vid)[key] == SHARED[key], f"{key} did not survive"


def test_and_comes_back_to_everybody_who_opens_the_board(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, admin_id, "משותפת", filters=dict(SHARED)).json()["id"]
    theirs = [v for v in _list(client, bid, guinea_id) if v["id"] == vid][0]
    assert theirs["filters"]["cols"] == SHARED["cols"]
    assert theirs["filters"]["sort"] == SHARED["sort"]


# ── the right-hand column: what stays with the person ──────────────────────
TEMPORARY = {
    "q": "טקסט חיפוש",                      # "לעולם אינו נשמר"
    "collapsed": [3, 7],                     # "קיפול הוא מצב מקומי בלבד"
    "groups_collapsed": {"3": True},
    "scroll": {"x": 420, "y": 1200},         # "אינם חלק מהתצורה"
    "scrollTop": 1200,
    "openSubs": [41, 42],                    # which sub-items are open
    "open_subs": [41],
    "selection": [1, 2, 3],
}


@pytest.mark.parametrize("key", sorted(TEMPORARY))
def test_nothing_temporary_is_stored_on_a_view(client, admin_id, key):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, f"זמני {key}",
              filters=dict(SHARED, **{key: TEMPORARY[key]})).json()["id"]
    assert key not in _stored(vid), f"{key} was stored on the view"
    assert _stored(vid)["cols"] == SHARED["cols"], "the shared half went with it"


@pytest.mark.parametrize("key", sorted(TEMPORARY))
def test_nor_by_saving_over_one(client, admin_id, key):
    """The create path and the save path are two doors into the same row."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, f"זמני {key}", filters=dict(SHARED)).json()["id"]
    r = _cfg(client, vid, admin_id, dict(SHARED, **{key: TEMPORARY[key]}))
    assert r.status_code == 200, r.text
    assert key not in _stored(vid)


def test_nor_by_copying_one_that_somehow_has_it(client, admin_id):
    """A row written before this rule existed, copied now, does not carry it
    into the new tab."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "המקור", filters=dict(SHARED)).json()["id"]
    with Session(cityos_main.engine) as db:
        v = db.query(SavedView).filter(SavedView.id == vid).first()
        v.filters = dict(v.filters, q="ישן", scroll={"y": 99})
        db.commit()

    c = client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id},
                    headers=_h(admin_id)).json()
    assert "q" not in _stored(c["id"]) and "scroll" not in _stored(c["id"])
    assert _stored(c["id"])["cols"] == SHARED["cols"]


# ── the rule itself ────────────────────────────────────────────────────────
def test_the_configuration_is_defined_as_what_is_kept(client, admin_id):
    """A strip-list would let the next thing the client invents ride along
    into everybody's tab. This case fails when the list grows, which is the
    point: adding to it is a decision, not a side effect."""
    assert set(cityos_main.VIEW_CONFIG_KEYS) == {
        "view", "cols", "adv", "people", "status", "priority", "links",
        # two keys for ordering, both of them ordering: "sort" is the toolbar's
        # old four fixed fields, carried by views saved before the column
        # headers took it over; "colSort" is the one every column offers now.
        "sort", "colSort"}
    assert "q" not in cityos_main.VIEW_CONFIG_KEYS


def test_an_invented_key_does_not_reach_the_next_person(client, admin_id, guinea_id):
    """The failure a keep-list prevents, acted out end to end."""
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, admin_id, "חדשנית",
              filters=dict(SHARED, somethingNew={"x": 1})).json()["id"]
    theirs = [v for v in _list(client, bid, guinea_id) if v["id"] == vid][0]
    assert "somethingNew" not in theirs["filters"]
