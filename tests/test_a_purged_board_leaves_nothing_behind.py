"""Destroying a board has to destroy everything that points at it.

The purge deleted three of the tables that carry a board id — tasks, groups,
members — and left the other nineteen. On SQLite that is invisible: foreign
keys are not enforced unless the connection asks for them, so the orphans sat
there and every test passed. QA runs PostgreSQL, where the keys are real, and
there it came out as:

    ForeignKeyViolation: update or delete on table "boards" violates foreign
    key constraint "board_views_board_id_fkey" on table "board_views"
    DETAIL:  Key (id)=(82) is still referenced from table "board_views".

A board_views row is written every time somebody opens a board, so every board
anyone had looked at was unpurgeable. And the purge of expired boards runs at
the top of the recycle bin's own endpoints — so one board past its window took
the whole bin down with it: GET /api/trash/boards answered 500 for everybody,
and a board could not be restored either, because restore sweeps first too.

Pinned here three ways: nothing is left behind, the schema decides what
"everything" means rather than a list somebody has to remember to extend, and
the purge is run once with the foreign keys actually switched on — which is
the only form of this test that would have failed before the fix.
"""
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

import main as cityos_main
from models import Board, BoardView, SavedView, EventOutbox, Task


def _mk_board(client, admin_id, name="לוח להשמדה"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _furnish(bid, admin_id):
    """Give the board the rows that were being left behind.

    board_views first and named first: it is the one the production failure
    pointed at, and it is written by the ordinary act of opening a board.
    """
    with Session(cityos_main.engine) as db:
        db.add(BoardView(board_id=bid, user_id=admin_id,
                         seen_at=datetime.now(timezone.utc)))
        db.add(SavedView(board_id=bid, owner_id=admin_id, name="חתך", kind="saved"))
        db.add(EventOutbox(kind="task.updated", board_id=bid, payload={}))
        db.commit()


def _board_tables():
    """Every table that names a board, straight out of the schema."""
    return [t for t in Board.metadata.sorted_tables
            if t.name != "boards"
            and ("board_id" in t.c or "target_board_id" in t.c)]


def _rows_naming(bid):
    """Which tables still hold a row pointing at this board."""
    left = {}
    with Session(cityos_main.engine) as db:
        for t in _board_tables():
            for col in ("board_id", "target_board_id"):
                if col not in t.c:
                    continue
                n = db.query(t).filter(t.c[col] == bid).count()
                if n:
                    left[f"{t.name}.{col}"] = n
    return left


def test_a_purged_board_leaves_no_row_naming_it(client, admin_id):
    bid = _mk_board(client, admin_id)
    client.post(f"/api/tasks", json={"board_id": bid, "title": "פריט", "user_id": admin_id})
    _furnish(bid, admin_id)
    assert _rows_naming(bid), "the fixture left nothing to clean up"

    client.delete(f"/api/boards/{bid}?user_id={admin_id}")          # to the bin
    r = client.delete(f"/api/trash/boards/{bid}?user_id={admin_id}")  # and gone
    assert r.status_code == 200, r.text

    left = _rows_naming(bid)
    assert not left, f"rows left pointing at a destroyed board: {left}"
    with Session(cityos_main.engine) as db:
        assert db.query(Board).filter(Board.id == bid).first() is None


def test_the_purge_asks_the_schema_what_everything_means(client, admin_id):
    """A list of tables goes stale; the schema does not.

    This is the part that keeps the bug from coming back the next time
    somebody adds a table with a board id in it — which is how it arrived in
    the first place.
    """
    src = (cityos_main.__file__)
    text = open(src, encoding="utf-8").read()
    assert "def _delete_rows_pointing_at_board(" in text, (
        "the purge went back to deleting a hand-written list of tables")
    assert "metadata.sorted_tables" in text, (
        "the sweep no longer takes its order from the schema, so it can delete "
        "a parent before its children")
    # every table that names a board must be reachable by the sweep's own test
    assert len(_board_tables()) > 3, "the schema check is not looking at anything"


@pytest.fixture
def foreign_keys_enforced():
    """SQLite with the keys switched on — QA's PostgreSQL, near enough.

    The pool is disposed on the way in and on the way out so no connection
    carries the pragma into another test.
    """
    engine = cityos_main.engine

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):                       # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    engine.dispose()
    try:
        yield
    finally:
        event.remove(engine, "connect", _fk_on)
        engine.dispose()


def test_the_purge_holds_when_the_foreign_keys_are_real(client, admin_id,
                                                        foreign_keys_enforced):
    """The production failure, reproduced: this is the one that used to raise."""
    bid = _mk_board(client, admin_id, "לוח עם מפתחות אמיתיים")
    _furnish(bid, admin_id)
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    r = client.delete(f"/api/trash/boards/{bid}?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert not _rows_naming(bid)


def test_the_bin_opens_even_with_a_board_past_its_window(client, admin_id,
                                                         foreign_keys_enforced):
    """One expired board used to answer 500 for the whole recycle bin.

    The bin purges what has expired before it lists what has not, so the board
    that could not be destroyed took every other board's restore with it.
    """
    bid = _mk_board(client, admin_id, "לוח שפג תוקפו")
    _furnish(bid, admin_id)
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        b.deleted_at = (datetime.now(timezone.utc).replace(tzinfo=None)
                        - timedelta(days=cityos_main.RECYCLE_BIN_DAYS + 1))
        db.commit()

    r = client.get(f"/api/trash/boards?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert bid not in [b["id"] for b in r.json()["boards"]]
    assert not _rows_naming(bid)
