"""שמות ומגבלות — מה הופך שני שמות ל"אותו שם", ומה התקרות.

A name is how somebody picks a tab out of a strip, so two tabs answering to
the same name is a failure of the only thing the strip does. The rule is
therefore about what COUNTS as the same name, and it is two steps: ends
trimmed, then compared without case for English. Hebrew has no case, so the
second step costs it nothing and is there for the English a municipality's
boards are full of.

The main table is in the comparison even though it has no row of its own. It
is the one tab that is always on the strip, and a saved view answering to its
name would make the strip ambiguous exactly where a reader cannot afford it.

The ceilings are technical — 80 characters, 100 active views per board with the
main table counted — and configurable. They exist so a board cannot be made
unusable, not to say anything about how many cuts a department should keep.
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


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _rename(client, vid, uid, name):
    return client.patch(f"/api/views/{vid}", json={"user_id": uid, "name": name},
                        headers=_h(uid))


# ── required, and unique ───────────────────────────────────────────────────
def test_a_name_is_required_only_where_somebody_is_giving_one(client, admin_id):
    """On the way in, no name means "name it for me" — see
    tests/test_view_create.py. On a RENAME it means "take its name away",
    which is the one reading that has to be refused."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "דחופים").json()["id"]
    assert _rename(client, vid, admin_id, "   ").status_code == 400
    assert _rename(client, vid, admin_id, "").status_code == 400


def test_two_views_on_one_board_cannot_share_a_name(client, admin_id):
    bid = _board(client, admin_id)
    assert _mk(client, bid, admin_id, "דחופים").status_code == 200
    r = _mk(client, bid, admin_id, "דחופים")
    assert r.status_code == 400 and "כבר יש תצוגה בשם" in r.json()["detail"]


def test_the_same_name_on_a_different_board_is_a_different_name(client, admin_id):
    """The rule is per board, because the strip is."""
    a = _board(client, admin_id, name="לוח א")
    b = _board(client, admin_id, name="לוח ב")
    assert _mk(client, a, admin_id, "דחופים").status_code == 200
    assert _mk(client, b, admin_id, "דחופים").status_code == 200


@pytest.mark.parametrize("first,second", [
    ("Urgent", "urgent"),
    ("urgent", "URGENT"),
    ("Urgent", "  Urgent  "),
    ("  דחופים", "דחופים  "),
    ("Open Bugs", "open bugs"),
])
def test_names_that_count_as_the_same_name(client, admin_id, first, second):
    bid = _board(client, admin_id)
    assert _mk(client, bid, admin_id, first).status_code == 200
    assert _mk(client, bid, admin_id, second).status_code == 400, f"{first!r} vs {second!r}"


def test_hebrew_is_left_exactly_as_typed(client, admin_id):
    """Casefolding must not quietly merge two different Hebrew names."""
    bid = _board(client, admin_id)
    assert _mk(client, bid, admin_id, "דחופים").status_code == 200
    assert _mk(client, bid, admin_id, "דחוף").status_code == 200
    assert sorted(v["name"] for v in _list(client, bid, admin_id)) == ["דחוף", "דחופים"]


def test_the_ends_are_trimmed_before_it_is_stored(client, admin_id):
    bid = _board(client, admin_id)
    v = _mk(client, bid, admin_id, "   דחופים   ").json()
    assert v["name"] == "דחופים"


# ── the main table holds its name ──────────────────────────────────────────
def test_the_main_tables_name_is_taken(client, admin_id):
    bid = _board(client, admin_id)
    r = _mk(client, bid, admin_id, cityos_main.MAIN_VIEW_NAME)
    assert r.status_code == 400 and "לטבלה הראשית" in r.json()["detail"]


def test_and_taken_by_the_same_comparison_as_everything_else(client, admin_id):
    bid = _board(client, admin_id)
    assert _mk(client, bid, admin_id, f"  {cityos_main.MAIN_VIEW_NAME}  ").status_code == 400


# ── renaming is held to the same rule ──────────────────────────────────────
def test_renaming_onto_another_views_name_is_refused(client, admin_id):
    bid = _board(client, admin_id)
    _mk(client, bid, admin_id, "ראשונה")
    vid = _mk(client, bid, admin_id, "שנייה").json()["id"]
    assert _rename(client, vid, admin_id, "ראשונה").status_code == 400
    assert _rename(client, vid, admin_id, "רִאשונה").status_code == 200, "a different name was refused"


def test_renaming_a_view_to_its_own_name_is_not_a_collision(client, admin_id):
    """It is the commonest rename of all — fixing the case or a stray space."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "דחופים").json()["id"]
    assert _rename(client, vid, admin_id, "דחופים").status_code == 200
    assert _rename(client, vid, admin_id, "  דחופים  ").status_code == 200


def test_a_name_freed_by_deleting_a_view_can_be_used_again(client, admin_id):
    """The rule is about ACTIVE views; one in the bin holds nothing."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "דחופים").json()["id"]
    assert _mk(client, bid, admin_id, "דחופים").status_code == 400
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    assert _mk(client, bid, admin_id, "דחופים").status_code == 200


def test_restoring_onto_a_name_taken_meanwhile_gets_a_suffix(client, admin_id):
    """"בשחזור עם שם תפוס תתווסף סיומת ייחודית."

    The bin is not a way around the uniqueness rule — but a restore is not
    refused over it either. Somebody asking for their view back gets their
    view back, under a name of its own.

    Renamed here and refused in _check_view_name, and the difference is who
    chose the name: silently renaming what a person just typed would be a lie,
    while a view returning from the bin has nobody standing over it."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "דחופים").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    assert _mk(client, bid, admin_id, "דחופים").status_code == 200

    r = client.post(f"/api/views/{vid}/restore", json={"user_id": admin_id}, headers=_h(admin_id))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "דחופים — משוחזרת"
    names = sorted(v["name"] for v in _list(client, bid, admin_id))
    assert names == ["דחופים", "דחופים — משוחזרת"], names


def test_a_restore_onto_a_free_name_keeps_the_name_it_had(client, admin_id):
    """The suffix is for a collision, not for every restore."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "דחופים").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    r = client.post(f"/api/views/{vid}/restore", json={"user_id": admin_id}, headers=_h(admin_id))
    assert r.json()["name"] == "דחופים"


# ── the length ceiling ─────────────────────────────────────────────────────
def test_a_name_at_the_ceiling_is_accepted(client, admin_id):
    bid = _board(client, admin_id)
    assert _mk(client, bid, admin_id, "א" * cityos_main.VIEW_NAME_MAX).status_code == 200


def test_a_longer_name_is_refused_rather_than_shortened(client, admin_id):
    """Silently trimming stores a name nobody typed — and one that can collide
    with a view that already exists, which is the worse half."""
    bid = _board(client, admin_id)
    r = _mk(client, bid, admin_id, "א" * (cityos_main.VIEW_NAME_MAX + 1))
    assert r.status_code == 400 and str(cityos_main.VIEW_NAME_MAX) in r.json()["detail"]
    assert _list(client, bid, admin_id) == []


# ── the suggestion a copy arrives with ─────────────────────────────────────
def test_a_copy_is_offered_a_free_name(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "המקור").json()["id"]
    first = client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id},
                        headers=_h(admin_id)).json()["name"]
    second = client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id},
                         headers=_h(admin_id)).json()["name"]
    assert first == "המקור — עותק" and second == "המקור — עותק 2"


def test_the_suggestion_skips_a_name_somebody_already_typed(client, admin_id):
    """A suggestion that came back refused by the rule that produced it would
    be the strip's own fault, not the user's."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "המקור").json()["id"]
    _mk(client, bid, admin_id, "המקור — עותק")
    assert client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id},
                       headers=_h(admin_id)).json()["name"] == "המקור — עותק 2"


def test_the_suggestion_compares_names_the_way_the_rule_does(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "Source").json()["id"]
    _mk(client, bid, admin_id, "source — עותק")           # same name, other case
    assert client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id},
                       headers=_h(admin_id)).json()["name"] == "Source — עותק 2"


def test_a_copy_of_a_very_long_name_still_fits(client, admin_id):
    """The suffix cannot push the suggestion past the ceiling — a suggestion
    is ours to shorten, unlike a name somebody typed."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "א" * cityos_main.VIEW_NAME_MAX).json()["id"]
    r = client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id},
                    headers=_h(admin_id))
    assert r.status_code == 200, r.text
    assert len(r.json()["name"]) <= cityos_main.VIEW_NAME_MAX
    assert r.json()["name"].endswith("עותק")


def test_a_name_sent_with_a_copy_is_held_to_the_same_rule(client, admin_id):
    """"וניתן לשנותו לפני שמירה" — and what arrives is checked like any other."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "המקור").json()["id"]
    assert client.post(f"/api/views/{vid}/duplicate",
                       json={"user_id": admin_id, "name": "בשם שלי"},
                       headers=_h(admin_id)).json()["name"] == "בשם שלי"
    r = client.post(f"/api/views/{vid}/duplicate",
                    json={"user_id": admin_id, "name": "המקור"}, headers=_h(admin_id))
    assert r.status_code == 400


# ── the ceilings are configurable ──────────────────────────────────────────
def test_both_ceilings_are_read_from_the_environment():
    """"אלה ערכים טכניים הניתנים להגדרה." Read as source rather than by
    restarting the app, which is the only other way to see a module constant
    change."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ.get("VIEW_NAME_MAX"' in src
    assert 'os.environ.get("VIEW_MAX_PER_BOARD"' in src
    assert 'os.environ.get("MAIN_VIEW_NAME"' in src
    assert cityos_main.VIEW_NAME_MAX == 80 and cityos_main.VIEW_MAX == 100, \
        "the documented starting values changed"
