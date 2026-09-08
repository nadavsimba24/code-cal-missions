"""Every board has the "מספר מזהה" column, not only the ones made recently.

New boards ship with it. A board created before it became a default simply does
not have it — which is why it shows on QA, where boards are made all the time,
and not on a production board that has been there for months. Reported exactly
that way: "this column should be a default, and it appears as a default only in
QA".

The backfill has a flag of its own. Every board that has ever started this
server carries `auto_cols_v1` from the earlier column backfill, so hanging this
one off that flag would reach new databases and skip every board it is for.
And it runs once per board: an admin who deletes the column must not find it
back after the next restart.
"""
import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from models import Board
from conftest import ADMIN_ID


def _cols(bid):
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        return [dict(c) for c in ((b.settings or {}).get("columns") or [])]


def _has_item_id(bid):
    return [c for c in _cols(bid) if c.get("type") == "item_id"]


@pytest.fixture
def old_board(client):
    """A board as it was created before the column was a default: no item_id
    column, and already flagged by the earlier auto-column backfill."""
    bid = client.post("/api/boards", json={"name": "לוח ותיק", "user_id": ADMIN_ID}).json()["id"]
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        s = dict(b.settings or {})
        s["columns"] = [c for c in (s.get("columns") or []) if c.get("type") != "item_id"]
        s["auto_cols_v1"] = True
        s.pop("item_id_col_v1", None)
        b.settings = s
        db.commit()
    assert not _has_item_id(bid)
    return bid


def test_a_new_board_is_born_with_it(client):
    bid = client.post("/api/boards", json={"name": "לוח חדש", "user_id": ADMIN_ID}).json()["id"]
    assert _has_item_id(bid), "a new board no longer ships with the column"


def test_a_board_that_predates_it_is_given_it(client, old_board):
    """The report."""
    cityos_main._backfill_item_id_column()
    got = _has_item_id(old_board)
    assert got, "the column never reached the boards that were missing it"
    assert got[0]["title"] == "מספר מזהה"


def test_the_earlier_backfill_s_flag_does_not_stand_in_for_this_one(client, old_board):
    """auto_cols_v1 is set on every board that has ever run this server; if it
    gated this step, the boards it is for would be exactly the ones skipped."""
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == old_board).first()
        assert (b.settings or {}).get("auto_cols_v1") is True
    cityos_main._backfill_item_id_column()
    assert _has_item_id(old_board)


def test_the_columns_a_board_already_had_are_left_alone(client, old_board):
    before = [c.get("id") for c in _cols(old_board)]
    cityos_main._backfill_item_id_column()
    after = [c.get("id") for c in _cols(old_board)]
    assert after[:len(before)] == before, "the board's own columns were reordered"
    assert len(after) == len(before) + 1


def test_a_deleted_column_stays_deleted(client, old_board):
    """Once per board. A column an admin removed must not come back on the next
    restart — that is the difference between a default and a magnet."""
    cityos_main._backfill_item_id_column()
    keep = [c for c in _cols(old_board) if c.get("type") != "item_id"]
    r = client.patch(f"/api/boards/{old_board}", json={"user_id": ADMIN_ID, "columns": keep})
    assert r.status_code == 200, r.text
    assert not _has_item_id(old_board)

    cityos_main._backfill_item_id_column()          # the next restart
    assert not _has_item_id(old_board), "the removed column came back"


def test_a_board_that_already_has_one_does_not_get_a_second(client):
    bid = client.post("/api/boards", json={"name": "כבר יש", "user_id": ADMIN_ID}).json()["id"]
    cityos_main._backfill_item_id_column()
    cityos_main._backfill_item_id_column()
    assert len(_has_item_id(bid)) == 1


def test_the_items_on_it_get_their_numbers(client, old_board):
    """The identifier is minted when a board carrying the column is read, so the
    column arrives already filled rather than showing "—" on every row."""
    client.post("/api/tasks", json={"board_id": old_board, "title": "פריט ותיק",
                                    "user_id": ADMIN_ID})
    cityos_main._backfill_item_id_column()
    tasks = client.get(f"/api/boards/{old_board}?user_id={ADMIN_ID}").json()["tasks"]
    assert tasks and all(t.get("item_uid") for t in tasks), \
        "the column is there but the rows have no number in it"
