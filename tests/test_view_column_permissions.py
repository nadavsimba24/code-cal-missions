"""עמודות מוגבלות וסינון שמור — מה תצוגה מראה למי שלא רואה את כל העמודות.

A column permission is already enforced on the data. A view is a second way to
reach the same column, and three of them are doors somebody could walk through
sideways:

  the saved FILTER — a condition on a column you may not see. Running it would
    answer a question about hidden data with a row set, and a row set is an
    answer. Dropping the rule instead is worse: inside an "or" group a dropped
    rule shows the whole board. So the view does not open, and does not copy.

  the message — "you may not see תקציב" and "…where תקציב > 50000" both tell
    you what the block exists to keep from you. It stays general, and the cut
    itself does not leave the server.

  the SAVE — somebody who was sent a table without those columns in it saves
    the table back. What returns has no opinion about the columns they never
    saw, and writing it as given deletes their widths, their order and their
    place on the hidden list. They did not ask for that and could not have
    known they were doing it.

And the fourth rule is about what a lock is NOT: it protects the shared
configuration, not the person's own temporary view of it and not item data.
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


def _column(client, bid, admin_id, title="תקציב", type_="number"):
    """Add one custom column. PATCH /columns is a full REPLACEMENT, so the
    board's existing columns — their ids and their permissions — have to be
    sent back with it. Posting only the new one silently drops the rest, which
    is how the first version of this helper deleted the column the fixture had
    just restricted and then "passed"."""
    cur = client.get(f"/api/boards/{bid}?user_id={admin_id}",
                     headers=_h(admin_id)).json().get("columns") or []
    r = client.patch(f"/api/boards/{bid}",
                     json={"columns": list(cur) + [{"type": type_, "title": title}],
                           "user_id": admin_id},
                     headers=_h(admin_id))
    assert r.status_code == 200, r.text
    assert len(r.json()["columns"]) == len(cur) + 1, "a column was lost"
    return r.json()["columns"][-1]["id"]


def _deny(client, bid, admin_id, col_id, uid):
    r = client.post(f"/api/boards/{bid}/columns/{col_id}/permissions",
                    json={"actor_id": admin_id, "user_id": uid, "perm": "none"},
                    headers=_h(admin_id))
    assert r.status_code == 200, r.text


def _cut_on(col_id, value=50000):
    return dict(CUT, adv={"op": "and", "rules": [{"field": col_id, "op": "gt", "v": value}]})


@pytest.fixture
def board(client, admin_id, guinea_id):
    """A board, an editor on it, and a column that editor may not see."""
    bid = _board(client, admin_id, invite=[guinea_id], role="editor")
    col = _column(client, bid, admin_id)
    _deny(client, bid, admin_id, col, guinea_id)
    return {"bid": bid, "col": col, "owner": admin_id, "blind": guinea_id}


# ── the saved filter ───────────────────────────────────────────────────────
def test_a_view_filtering_on_a_forbidden_column_does_not_open(client, board):
    vid = _mk(client, board["bid"], board["owner"], "לפי תקציב",
              filters=_cut_on(board["col"])).json()["id"]
    assert vid

    seen = [v for v in _list(client, board["bid"], board["blind"]) if v["id"] == vid]
    assert seen, "the tab vanished instead of being blocked"
    assert seen[0]["blocked"] is True


def test_the_block_does_not_say_which_column_or_what_the_condition_was(client, board):
    """Both halves of the disclosure the block exists to prevent."""
    # a neutral name: what the server must not reveal is the column and the
    # condition, not a title somebody chose to type
    vid = _mk(client, board["bid"], board["owner"], "חיתוך",
              filters=_cut_on(board["col"], 777777)).json()["id"]
    blob = str([v for v in _list(client, board["bid"], board["blind"]) if v["id"] == vid])
    assert "תקציב" not in blob, "the message named the column"
    assert board["col"] not in blob, "the column id travelled"
    assert "777777" not in blob, "the condition travelled"


def test_the_owner_of_the_board_opens_it_normally(client, board):
    """The block is about this reader, not about the view."""
    vid = _mk(client, board["bid"], board["owner"], "לפי תקציב",
              filters=_cut_on(board["col"])).json()["id"]
    mine = [v for v in _list(client, board["bid"], board["owner"]) if v["id"] == vid][0]
    assert mine["blocked"] is False
    assert mine["filters"]["adv"]["rules"][0]["field"] == board["col"]


def test_a_blocked_view_is_not_copied_either(client, board):
    """A copy is yours, and the rule naming the column comes with it."""
    vid = _mk(client, board["bid"], board["owner"], "לפי תקציב",
              filters=_cut_on(board["col"])).json()["id"]
    r = client.post(f"/api/views/{vid}/duplicate",
                    json={"user_id": board["blind"]}, headers=_h(board["blind"]))
    assert r.status_code == 403
    assert "תקציב" not in r.text


def test_a_blocked_view_is_not_saved_over_either(client, board):
    """The same disclosure from the other side: overwriting the rule you
    cannot see would tell you it was there."""
    vid = _mk(client, board["bid"], board["owner"], "לפי תקציב",
              filters=_cut_on(board["col"])).json()["id"]
    r = client.patch(f"/api/views/{vid}",
                     json={"user_id": board["blind"], "filters": dict(CUT)},
                     headers=_h(board["blind"]))
    assert r.status_code == 403


def test_a_view_filtering_only_on_columns_everybody_sees_is_untouched(client, board):
    vid = _mk(client, board["bid"], board["owner"], "רגילה").json()["id"]
    v = [x for x in _list(client, board["bid"], board["blind"]) if x["id"] == vid][0]
    assert v["blocked"] is False and v["filters"]["adv"] == CUT["adv"]


# ── the layout that does not travel ────────────────────────────────────────
def test_settings_for_a_forbidden_column_are_not_sent_to_the_browser(client, board):
    cols = {"order": ["item", board["col"], "status"],
            "hidden": [board["col"]], "widths": {"item": 300, board["col"]: 190}}
    vid = _mk(client, board["bid"], board["owner"], "עם תקציב",
              filters=dict(CUT, cols=cols)).json()["id"]

    theirs = [v for v in _list(client, board["bid"], board["blind"]) if v["id"] == vid][0]
    got = theirs["filters"]["cols"]
    assert board["col"] not in got["order"]
    assert board["col"] not in got["hidden"]
    assert board["col"] not in got["widths"]
    assert got["order"] == ["item", "status"] and got["widths"] == {"item": 300}

    mine = [v for v in _list(client, board["bid"], board["owner"]) if v["id"] == vid][0]
    assert mine["filters"]["cols"] == cols, "the owner's own view was redacted too"


# ── saving part of a table must not delete the rest of it ──────────────────
def test_saving_a_partial_table_keeps_the_settings_that_were_withheld(client, board):
    cols = {"order": ["item", board["col"], "status"],
            "hidden": [board["col"]], "widths": {"item": 300, board["col"]: 190}}
    vid = _mk(client, board["bid"], board["owner"], "עם תקציב",
              filters=dict(CUT, cols=cols)).json()["id"]

    # what the blind editor was sent, saved straight back with one width changed
    theirs = [v for v in _list(client, board["bid"], board["blind"]) if v["id"] == vid][0]
    sent = dict(theirs["filters"])
    sent["cols"] = dict(sent["cols"], widths=dict(sent["cols"]["widths"], item=360))
    r = client.patch(f"/api/views/{vid}", json={"user_id": board["blind"], "filters": sent},
                     headers=_h(board["blind"]))
    assert r.status_code == 200, r.text

    with Session(cityos_main.engine) as db:
        stored = db.query(SavedView).filter(SavedView.id == vid).first().filters["cols"]
    assert stored["widths"][board["col"]] == 190, "a width nobody could see was deleted"
    assert stored["widths"]["item"] == 360, "the change that WAS made did not land"
    assert board["col"] in stored["hidden"], "a hidden flag nobody could see was deleted"
    assert board["col"] in stored["order"], "a column nobody could see left the order"


def test_the_withheld_column_keeps_its_place_in_the_order(client, board):
    """Not merely present — where it was. Appending it would silently reorder
    the table for the people who CAN see it."""
    other = _column(client, board["bid"], board["owner"], title="מחלקה", type_="text")
    cols = {"order": ["item", board["col"], other, "status"], "hidden": [], "widths": {}}
    vid = _mk(client, board["bid"], board["owner"], "עם תקציב",
              filters=dict(CUT, cols=cols)).json()["id"]

    theirs = [v for v in _list(client, board["bid"], board["blind"]) if v["id"] == vid][0]
    assert theirs["filters"]["cols"]["order"] == ["item", other, "status"]
    r = client.patch(f"/api/views/{vid}",
                     json={"user_id": board["blind"], "filters": theirs["filters"]},
                     headers=_h(board["blind"]))
    assert r.status_code == 200, r.text

    with Session(cityos_main.engine) as db:
        stored = db.query(SavedView).filter(SavedView.id == vid).first().filters["cols"]
    assert stored["order"] == ["item", board["col"], other, "status"], stored["order"]


def test_a_reorder_by_somebody_who_sees_part_of_the_table_still_takes_effect(client, board):
    """The merge must not become "ignore what they did"."""
    other = _column(client, board["bid"], board["owner"], title="מחלקה", type_="text")
    cols = {"order": ["item", board["col"], other, "status"], "hidden": [], "widths": {}}
    vid = _mk(client, board["bid"], board["owner"], "עם תקציב",
              filters=dict(CUT, cols=cols)).json()["id"]

    theirs = [v for v in _list(client, board["bid"], board["blind"]) if v["id"] == vid][0]
    moved = dict(theirs["filters"])
    moved["cols"] = dict(moved["cols"], order=["item", "status", other])
    client.patch(f"/api/views/{vid}", json={"user_id": board["blind"], "filters": moved},
                 headers=_h(board["blind"]))

    with Session(cityos_main.engine) as db:
        stored = db.query(SavedView).filter(SavedView.id == vid).first().filters["cols"]
    assert [c for c in stored["order"] if c != board["col"]] == ["item", "status", other]
    assert board["col"] in stored["order"]


# ── what a lock is not ─────────────────────────────────────────────────────
def test_a_lock_does_not_reach_item_data(client, board):
    """"נעילה מגינה על התצורה המשותפת. היא אינה מונעת התאמות זמניות או עריכת
    נתוני פריטים בהתאם להרשאות." A locked view is a locked tab, not a frozen
    board — the editor who cannot touch its settings still edits the items."""
    bid, blind, owner = board["bid"], board["blind"], board["owner"]
    vid = _mk(client, bid, owner, "נעולה").json()["id"]
    client.patch(f"/api/views/{vid}", json={"user_id": owner, "locked": True}, headers=_h(owner))

    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט", "user_id": owner},
                      headers=_h(owner)).json()["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"title": "שם חדש", "user_id": blind},
                     headers=_h(blind))
    assert r.status_code == 200, r.text

    # and the view's own settings are still refused to them
    assert client.patch(f"/api/views/{vid}", json={"user_id": blind, "name": "אחרת"},
                        headers=_h(blind)).status_code == 403


def test_a_lock_does_not_stop_a_temporary_filter(client, board):
    """A temporary cut never reaches the view at all — it is asked of the
    board. The lock is on the stored configuration, not on looking."""
    bid, blind, owner = board["bid"], board["blind"], board["owner"]
    vid = _mk(client, bid, owner, "נעולה").json()["id"]
    client.patch(f"/api/views/{vid}", json={"user_id": owner, "locked": True}, headers=_h(owner))

    # `filter`, which is the key the endpoint reads; `adv` is the name the
    # saved view stores it under and sends nothing at all here
    r = client.post(f"/api/boards/{bid}/items/query",
                    json={"user_id": blind, "filter": {"op": "and", "rules": [
                        {"field": "status", "op": "ne", "v": "done"}]},
                        "today": "2026-10-20", "tz_offset": 180},
                    headers=_h(blind))
    assert r.status_code == 200, r.text
    assert r.json()["conditions"] == 1, "the temporary filter never reached the server"


# ── creating, copying, and the escape hatch from a locked view ─────────────
def test_creating_a_view_is_validated_the_way_copying_one_is(client, board):
    """"תנאי גישה והאימות זהים לאלה של שכפול."

    Duplicating a view whose filter names a forbidden column is refused. Were
    creation not held to the same rule, an editor could post that same filter
    as a new view of their own and run it — the block with one extra step."""
    r = _mk(client, board["bid"], board["blind"], "משלי",
            filters=_cut_on(board["col"]))
    assert r.status_code == 403, r.text
    assert "תקציב" not in r.text and board["col"] not in r.text

    with Session(cityos_main.engine) as db:
        assert db.query(SavedView).filter(SavedView.board_id == board["bid"],
                                          SavedView.name == "משלי").count() == 0


def test_the_board_owner_may_still_create_that_cut(client, board):
    """The validation is about the person, not about the filter."""
    assert _mk(client, board["bid"], board["owner"], "שלי",
               filters=_cut_on(board["col"])).status_code == 200


def test_save_as_new_is_how_an_editor_works_from_a_locked_view(client, board):
    """"בתצוגה נעולה, עורך יוכל להשתמש בשמירה כתצוגה חדשה במקום לשנות את
    המקור." The original is refused to them; their own copy is not."""
    bid, blind, owner = board["bid"], board["blind"], board["owner"]
    vid = _mk(client, bid, owner, "נעולה").json()["id"]
    client.patch(f"/api/views/{vid}", json={"user_id": owner, "locked": True},
                 headers=_h(owner))

    assert client.patch(f"/api/views/{vid}", json={"user_id": blind, "name": "לא"},
                        headers=_h(blind)).status_code == 403
    mine = _mk(client, bid, blind, "הגרסה שלי")
    assert mine.status_code == 200, mine.text
    assert mine.json()["locked"] is False, "the copy arrived locked"

    # and duplicate — the other route off a locked view — is open to them too
    assert client.post(f"/api/views/{vid}/duplicate", json={"user_id": blind},
                       headers=_h(blind)).status_code == 200


def test_a_copy_is_a_new_tab_and_grants_nothing(client, board):
    """"אין להעתיק נתונים או להקנות הרשאות חדשות." The copy carries the
    configuration and only that: a new id, a new owner, shared, unlocked,
    unpinned — and no column the copier could not already see."""
    bid, blind, owner = board["bid"], board["blind"], board["owner"]
    other = _column(client, bid, owner, title="מחלקה", type_="text")
    cols = {"order": ["item", board["col"], other], "hidden": [],
            "widths": {board["col"]: 190, other: 140}}
    vid = _mk(client, bid, owner, "המקור", filters=dict(CUT, cols=cols)).json()["id"]
    client.patch(f"/api/views/{vid}", json={"user_id": owner, "pinned": True},
                 headers=_h(owner))

    c = client.post(f"/api/views/{vid}/duplicate", json={"user_id": blind},
                    headers=_h(blind)).json()
    assert c["id"] != vid
    assert c["owner_id"] == blind
    assert c["visibility"] == "public" and c["locked"] is False and c["pinned"] is False

    # the stored copy keeps the full configuration — copying must not be a way
    # to STRIP the settings of a column the copier cannot see
    with Session(cityos_main.engine) as db:
        stored = db.query(SavedView).filter(SavedView.id == c["id"]).first().filters
    assert stored["cols"]["widths"][board["col"]] == 190

    # ...and the copier is still not shown them
    theirs = [v for v in _list(client, bid, blind) if v["id"] == c["id"]][0]
    assert board["col"] not in theirs["filters"]["cols"]["widths"]
    assert board["col"] not in theirs["filters"]["cols"]["order"]
