"""An event that has gone out must not go out again on the next board read.

The outbox is at-least-once by design: a row is marked sent only after the bus
has taken it. The mark was never committed on the path that matters, though.
`_sweep_due_date_automations` drains the outbox at the top and then returns
early in three places — this board has no date rules, nothing is due, nothing
fired — and none of those reaches a commit. The session is discarded, the rows
are unsent again, and the next read publishes exactly the same events.

The next read is never far away, because the browser refetches the board
whenever an event arrives — an `automation.ran` even for the person who caused
it. So: read → publish → the client refetches → read → publish, at the speed of
a round trip. On QA two boards sat at some fifty-five reads a minute for hours
— 3,176 board fetches against 24 actual board opens — and what that looks like
to the person using it is a board that will not stop jumping.

The sweep is exercised directly here as well as through the endpoint, and on
purpose: a board whose items are still being issued their "מספר מזהה" commits
for that on its way past, which saved the outbox marks by accident and hid
this on exactly the boards that are new. The boards it bit were the settled
ones, where nothing else on the read writes anything.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import EventOutbox


def _mk_board(client, admin_id):
    return client.post("/api/boards", json={"name": "לוח עם תיבת יוצא",
                                            "user_id": admin_id}).json()["id"]


def _queue(bid, kind="automation.ran"):
    with Session(cityos_main.engine) as db:
        row = EventOutbox(kind=kind, board_id=bid, payload={})
        db.add(row)
        db.commit()
        return row.id


def _sent_at(row_id):
    with Session(cityos_main.engine) as db:
        return db.query(EventOutbox).filter(EventOutbox.id == row_id).first().sent_at


def _counting_bus():
    """Swap the bus for a counter. Returns (list, restore)."""
    seen = []
    real = cityos_main.bus.publish
    cityos_main.bus.publish = lambda kind, **kw: seen.append((kind, kw.get("board_id")))
    return seen, (lambda: setattr(cityos_main.bus, "publish", real))


def _sweep(bid):
    """One board read's worth of sweeping, in a session of its own — which is
    what the endpoint does, and the session being discarded afterwards is the
    whole of the bug."""
    with Session(cityos_main.engine) as db:
        cityos_main._sweep_due_date_automations(db, bid, None)


def test_the_sweep_saves_the_fact_that_the_event_went_out(client, admin_id):
    """The mark is the whole of "it was sent", so it has to survive the read."""
    bid = _mk_board(client, admin_id)
    row_id = _queue(bid)
    assert _sent_at(row_id) is None
    seen, restore = _counting_bus()
    try:
        _sweep(bid)
    finally:
        restore()
    assert seen, "nothing was published — the fixture is not exercising the drain"
    assert _sent_at(row_id) is not None, (
        "the row was published and left unsent in the database, so the next "
        "read publishes it again")


def test_sweeping_twice_publishes_a_queued_event_once(client, admin_id):
    bid = _mk_board(client, admin_id)
    _queue(bid)
    seen, restore = _counting_bus()
    try:
        for _ in range(3):
            _sweep(bid)
    finally:
        restore()
    mine = [s for s in seen if s[1] == bid]
    assert len(mine) == 1, (
        f"the same queued event went out {len(mine)} times — every board read "
        "republishes it, and every delivery makes the browser read the board "
        "again")


def test_reading_the_board_twice_publishes_a_queued_event_once(client, admin_id):
    """The same thing through the endpoint, which is where it was happening.

    The board is read once BEFORE the row is queued, so whatever a first read
    writes for itself is already written and this one reads a settled board —
    the state every board on QA was in.
    """
    bid = _mk_board(client, admin_id)
    client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                    "user_id": admin_id})
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    _queue(bid)
    seen, restore = _counting_bus()
    try:
        for _ in range(3):
            assert client.get(f"/api/boards/{bid}?user_id={admin_id}").status_code == 200
    finally:
        restore()
    mine = [s for s in seen if s[1] == bid]
    assert len(mine) == 1, f"the board read republished the same event {len(mine)} times"


def test_a_board_with_nothing_queued_is_left_alone(client, admin_id):
    """The commit is for work that was done, not a write on every board read."""
    bid = _mk_board(client, admin_id)
    seen, restore = _counting_bus()
    try:
        _sweep(bid)
    finally:
        restore()
    assert not seen
