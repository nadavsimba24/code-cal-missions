"""העמודות האוטומטיות בכל לוח — "מועד יצירה" ו"יוצר הרשומה".

Every board carries both, not only ones created after the feature existed.
They are derived from the item, so adding the column is the whole job — the
values are right for items that predate it. The backfill runs once per board,
so an admin who removes a column does not get it back on the next restart.
"""
import main as cityos_main
from models import Board
from sqlalchemy.orm import Session


def _cols(bid):
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        return [dict(c) for c in ((b.settings or {}).get("columns") or [])]


def _set_cols(bid, cols, mark=None):
    """Put a board into a pre-backfill shape."""
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        s = dict(b.settings or {})
        s["columns"] = cols
        s.pop("auto_cols_v1", None)
        if mark is not None:
            s["auto_cols_v1"] = mark
        b.settings = s
        db.commit()


def _board(client, admin_id, name="לוח ותיק"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def test_every_board_ends_up_with_both_automatic_columns(client, admin_id):
    with Session(cityos_main.engine) as db:
        ids = [b.id for b in db.query(Board).all()]
    cityos_main._backfill_auto_columns()
    for bid in ids:
        types = {c["type"] for c in _cols(bid)}
        assert "created_at" in types and "created_by" in types, (bid, types)


def test_a_board_with_no_columns_at_all_gets_them(client, admin_id):
    bid = _board(client, admin_id)
    _set_cols(bid, [])
    cityos_main._backfill_auto_columns()
    got = {(c["type"], c["title"]) for c in _cols(bid)}
    assert ("created_at", "מועד יצירה") in got
    assert ("created_by", "יוצר הרשומה") in got


def test_existing_columns_are_kept_and_the_new_ones_appended(client, admin_id):
    bid = _board(client, admin_id)
    _set_cols(bid, [{"id": "col_keep", "type": "text", "title": "הערות"}])
    cityos_main._backfill_auto_columns()
    cols = _cols(bid)
    assert cols[0]["id"] == "col_keep"                      # layout is not disturbed
    assert [c["type"] for c in cols[1:]] == ["created_at", "created_by"]


def test_the_legacy_people_creator_column_is_upgraded_in_place(client, admin_id):
    """Old boards carry it as a people column that only filled on creation."""
    bid = _board(client, admin_id)
    _set_cols(bid, [{"id": "sys_created_by", "type": "people", "title": "יוצר הרשומה"}])
    cityos_main._backfill_auto_columns()
    cols = _cols(bid)
    creator = [c for c in cols if c["id"] == "sys_created_by"]
    assert len(creator) == 1 and creator[0]["type"] == "created_by"
    assert len([c for c in cols if c["type"] == "created_by"]) == 1   # no duplicate


def test_a_removed_column_does_not_come_back(client, admin_id):
    """The backfill is once per board — deleting a column is respected."""
    bid = _board(client, admin_id)
    cityos_main._backfill_auto_columns()
    kept = [c for c in _cols(bid) if c["type"] != "created_at"]
    with Session(cityos_main.engine) as db:                  # admin removes it
        b = db.query(Board).filter(Board.id == bid).first()
        s = dict(b.settings or {}); s["columns"] = kept; b.settings = s; db.commit()
    cityos_main._backfill_auto_columns()                     # next server boot
    assert "created_at" not in {c["type"] for c in _cols(bid)}


def test_the_backfill_is_idempotent(client, admin_id):
    bid = _board(client, admin_id)
    _set_cols(bid, [])
    cityos_main._backfill_auto_columns()
    once = _cols(bid)
    cityos_main._backfill_auto_columns()
    cityos_main._backfill_auto_columns()
    assert _cols(bid) == once


def test_items_that_predate_the_column_still_show_creator_and_time(client, admin_id):
    bid = _board(client, admin_id)
    _set_cols(bid, [])
    t = client.post("/api/tasks", json={"board_id": bid, "title": "פריט ותיק",
                                        "user_id": admin_id}).json()
    cityos_main._backfill_auto_columns()
    fresh = [x for x in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"]
             if x["id"] == t["id"]][0]
    assert fresh["created_by"] == admin_id and fresh["created_at"]
