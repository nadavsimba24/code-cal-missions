"""Group — live updates: events as the doorbell, REST as the source of truth.

The stream carries no data, only "something changed". These cover the piece that
actually enforces access (the single-item refetch), the bus semantics that keep
a slow client from hurting the server, and the fact that the stream itself is
closed to anonymous callers.
"""
import asyncio

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from events import Bus
from models import Task


def _mk(client, admin_id, title="פריט חי"):
    bid = client.post("/api/boards", json={"name": "לוח אירועים", "user_id": admin_id}).json()["id"]
    tid = client.post("/api/tasks", json={"board_id": bid, "title": title, "user_id": admin_id}).json()["id"]
    return bid, tid


# ── the refetch step: this is where permissions are enforced ──────────
def test_a_single_item_can_be_refetched(client, admin_id):
    bid, tid = _mk(client, admin_id)
    r = client.get(f"/api/tasks/{tid}?user_id={admin_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == tid and body["board_id"] == bid
    assert "my_perm" in body            # serialized exactly like the board serializes it


def test_refetching_an_item_on_a_board_you_are_not_on_is_refused(client, admin_id, guinea_id):
    _, tid = _mk(client, admin_id)
    assert client.get(f"/api/tasks/{tid}?user_id={guinea_id}").status_code == 403


def test_refetching_an_item_you_were_denied_is_refused(client, admin_id, guinea_id):
    """A per-item override of "none" must hide the item from the refetch too —
    otherwise an event id would be enough to read it."""
    bid, tid = _mk(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert client.get(f"/api/tasks/{tid}?user_id={guinea_id}").status_code == 200
    client.post(f"/api/tasks/{tid}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"})
    assert client.get(f"/api/tasks/{tid}?user_id={guinea_id}").status_code == 403


def test_refetching_a_missing_item_is_a_404(client, admin_id):
    assert client.get(f"/api/tasks/99999999?user_id={admin_id}").status_code == 404


def test_an_item_on_a_binned_board_is_gone(client, admin_id):
    """A board in the recycle bin must not stay readable one item at a time."""
    bid, tid = _mk(client, admin_id)
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    assert client.get(f"/api/tasks/{tid}?user_id={admin_id}").status_code == 404


# ── the stream ────────────────────────────────────────────────────────
def test_the_event_stream_is_closed_to_anonymous_callers(client):
    assert client.get("/api/events", headers={"X-CityOS-User": ""}).status_code == 401


# ── bus semantics ─────────────────────────────────────────────────────
def test_publishing_without_a_running_loop_is_a_no_op():
    """Publish is called from sync handlers; if there is no loop to hop to it
    must return quietly rather than take down the write that just succeeded."""
    b = Bus()
    b.publish("task.changed", board_id=1, task_id=2)      # must not raise


def test_every_subscriber_gets_the_event():
    async def go():
        b = Bus(); b.bind_loop(asyncio.get_running_loop())
        q1, q2 = b.subscribe(), b.subscribe()
        b.publish("task.changed", board_id=7, task_id=42, actor_id=3)
        await asyncio.sleep(0)                            # let call_soon_threadsafe run
        a, c = q1.get_nowait(), q2.get_nowait()
        assert a["type"] == c["type"] == "task.changed"
        assert a["board_id"] == 7 and a["task_id"] == 42 and a["actor_id"] == 3
        assert a["seq"] < b.publish.__self__._seq.__next__()   # seq advances
    asyncio.run(go())


def test_an_unsubscribed_queue_stops_receiving():
    async def go():
        b = Bus(); b.bind_loop(asyncio.get_running_loop())
        q = b.subscribe(); b.unsubscribe(q)
        b.publish("task.changed", board_id=1)
        await asyncio.sleep(0)
        assert q.empty()
        assert b.subscribers == 0
    asyncio.run(go())


def test_a_client_that_falls_behind_is_told_to_resync():
    """The backlog is dropped rather than grown: on overflow the queue is
    emptied and replaced by one "resync". Events published afterwards keep
    flowing normally — the client resyncs, then applies the newer ones."""
    async def go():
        import events as ev
        b = Bus(); b.bind_loop(asyncio.get_running_loop())
        q = b.subscribe()
        overshoot = 5
        for i in range(ev.QUEUE_MAX + overshoot):
            b.publish("task.changed", board_id=1, task_id=i)
        await asyncio.sleep(0)
        # memory is bounded — the backlog never grows past the cap
        assert q.qsize() <= ev.QUEUE_MAX
        drained = []
        while not q.empty():
            drained.append(q.get_nowait())
        assert drained[0]["type"] == "resync", "the overflow must announce itself first"
        # and the queue collapsed rather than kept every stale event
        assert len(drained) == overshoot, drained
    asyncio.run(go())


def test_events_can_be_switched_off_without_a_redeploy(monkeypatch):
    async def go():
        import events as ev
        b = Bus(); b.bind_loop(asyncio.get_running_loop())
        q = b.subscribe()
        monkeypatch.setattr(ev, "EVENTS_ENABLED", False)
        b.publish("task.changed", board_id=1)
        await asyncio.sleep(0)
        assert q.empty()
    asyncio.run(go())


# ── the write path still publishes ────────────────────────────────────
def test_updating_an_item_announces_it(client, admin_id):
    """The event must be published after the commit, carrying ids only."""
    bid, tid = _mk(client, admin_id)
    seen = []
    cityos_main.bus.bind_loop(asyncio.new_event_loop())    # a loop that never runs
    cityos_main.bus._fanout = lambda ev: seen.append(ev)   # observe fan-out directly
    orig = cityos_main.bus._loop.call_soon_threadsafe
    cityos_main.bus._loop.call_soon_threadsafe = lambda fn, ev: fn(ev)

    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"title": "שם חדש"})
    cityos_main.bus._loop.call_soon_threadsafe = orig

    changed = [e for e in seen if e["type"] == "task.changed" and e["task_id"] == tid]
    assert changed, f"no task.changed published, saw: {seen}"
    ev = changed[0]
    assert ev["board_id"] == bid and ev["actor_id"] == admin_id
    # the envelope carries ids, never content
    assert set(ev) == {"seq", "type", "board_id", "task_id", "actor_id"}
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.id == tid).first().title == "שם חדש"
