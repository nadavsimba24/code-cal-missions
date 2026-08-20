"""Group — recycle bin (סל מחזור): a deleted board is restorable for 60 days.

Deleting a board used to destroy it and everything under it. It is now a soft
delete: the board keeps its groups, items, comments and memberships and simply
stops being listed, so a restore is lossless.
"""
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
import main as cityos_main
from models import Board, Task, Group, BoardMember


def _mk_board(client, admin_id, name="לוח לסל מחזור"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _bin_ids(client, uid):
    return [b["id"] for b in client.get(f"/api/trash/boards?user_id={uid}").json()["boards"]]


def _backdate(bid, days):
    """Age a binned board so expiry can be tested without waiting."""
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        b.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        db.commit()


def test_delete_keeps_the_board_and_its_content(client, admin_id):
    """A deleted board is stamped, not destroyed — nothing under it is removed."""
    bid = _mk_board(client, admin_id)
    with Session(cityos_main.engine) as db:
        groups = db.query(Group).filter(Group.board_id == bid).count()
        members = db.query(BoardMember).filter(BoardMember.board_id == bid).count()

    assert client.delete(f"/api/boards/{bid}?user_id={admin_id}").status_code == 200
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        assert b is not None and b.deleted_at is not None
        assert b.deleted_by == admin_id
        assert db.query(Group).filter(Group.board_id == bid).count() == groups
        assert db.query(BoardMember).filter(BoardMember.board_id == bid).count() == members


def test_a_binned_board_disappears_from_every_listing(client, admin_id):
    bid = _mk_board(client, admin_id)
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    assert bid not in [b["id"] for b in client.get(f"/api/boards?user_id={admin_id}").json()]
    # and cannot be opened by guessing its id
    assert client.get(f"/api/boards/{bid}?user_id={admin_id}").status_code == 404


def test_the_bin_lists_it_with_the_time_left(client, admin_id):
    bid = _mk_board(client, admin_id)
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    d = client.get(f"/api/trash/boards?user_id={admin_id}").json()
    assert d["retention_days"] == cityos_main.RECYCLE_BIN_DAYS
    entry = next(b for b in d["boards"] if b["id"] == bid)
    assert entry["days_left"] == cityos_main.RECYCLE_BIN_DAYS
    assert entry["deleted_by"] == admin_id


def test_restore_brings_the_board_back_intact(client, admin_id):
    bid = _mk_board(client, admin_id)
    client.post("/api/tasks", json={"board_id": bid, "title": "פריט לבדיקה", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        tasks = db.query(Task).filter(Task.board_id == bid).count()
    assert tasks >= 1

    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    assert client.post(f"/api/trash/boards/{bid}/restore?user_id={admin_id}").status_code == 200

    assert bid in [b["id"] for b in client.get(f"/api/boards?user_id={admin_id}").json()]
    assert client.get(f"/api/boards/{bid}?user_id={admin_id}").status_code == 200
    assert bid not in _bin_ids(client, admin_id)
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.board_id == bid).count() == tasks


def test_a_board_past_its_window_is_purged_for_good(client, admin_id):
    bid = _mk_board(client, admin_id)
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    _backdate(bid, cityos_main.RECYCLE_BIN_DAYS + 1)

    assert bid not in _bin_ids(client, admin_id)        # reading the bin purges it
    with Session(cityos_main.engine) as db:
        assert db.query(Board).filter(Board.id == bid).first() is None
        assert db.query(Task).filter(Task.board_id == bid).count() == 0
        assert db.query(Group).filter(Group.board_id == bid).count() == 0
    assert client.post(f"/api/trash/boards/{bid}/restore?user_id={admin_id}").status_code == 404


def test_the_day_before_expiry_it_is_still_restorable(client, admin_id):
    """Boundary: the retention window must not expire a day early."""
    bid = _mk_board(client, admin_id)
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    _backdate(bid, cityos_main.RECYCLE_BIN_DAYS - 1)
    entry = next(b for b in client.get(f"/api/trash/boards?user_id={admin_id}").json()["boards"]
                 if b["id"] == bid)
    assert entry["days_left"] == 1
    assert client.post(f"/api/trash/boards/{bid}/restore?user_id={admin_id}").status_code == 200


def test_purge_destroys_it_on_request(client, admin_id):
    bid = _mk_board(client, admin_id)
    # a live board is not in the bin, so it cannot be purged
    assert client.delete(f"/api/trash/boards/{bid}?user_id={admin_id}").status_code == 400
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    assert client.delete(f"/api/trash/boards/{bid}?user_id={admin_id}").status_code == 200
    with Session(cityos_main.engine) as db:
        assert db.query(Board).filter(Board.id == bid).first() is None


def test_a_non_member_can_neither_see_nor_restore_it(client, admin_id, guinea_id):
    """The bin must not leak boards the user was never invited to."""
    bid = _mk_board(client, admin_id, "לוח פרטי")
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    assert bid not in _bin_ids(client, guinea_id)
    assert client.post(f"/api/trash/boards/{bid}/restore?user_id={guinea_id}").status_code == 403
    assert client.delete(f"/api/trash/boards/{bid}?user_id={guinea_id}").status_code == 403


def test_a_board_viewer_may_not_restore(client, admin_id, guinea_id):
    """Restoring is a destructive-scope action — viewers must not have it."""
    bid = _mk_board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    assert bid not in _bin_ids(client, guinea_id)
    assert client.post(f"/api/trash/boards/{bid}/restore?user_id={guinea_id}").status_code == 403


def test_a_board_admin_may_restore(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    assert bid in _bin_ids(client, guinea_id)
    assert client.post(f"/api/trash/boards/{bid}/restore?user_id={guinea_id}").status_code == 200


def test_the_bin_is_closed_to_anonymous_callers(client):
    assert client.get("/api/trash/boards", headers={"X-CityOS-User": ""}).status_code == 401
