"""Group — live updates: events as the doorbell, REST as the source of truth.

The stream carries no data, only "something changed". These cover the piece that
actually enforces access (the single-item refetch), the bus semantics that keep
a slow client from hurting the server, and the fact that the stream itself is
closed to anonymous callers.
"""
import asyncio
import json
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from events import Bus
from models import Task

ROOT = pathlib.Path(__file__).resolve().parent.parent


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


# ── the wire ──────────────────────────────────────────────────────────────
# Everything above this line tests the bus and the refetch — which half of
# the feature works was never in doubt. What nothing tested was the four
# lines that go down the socket, and that is where live updates were broken:
# the stream named every event (`event: task.changed`), and a named frame is
# not delivered to EventSource.onmessage, which is the only handler the
# browser has. The bus fanned out correctly, the outbox drained correctly,
# the frames arrived correctly, and the client discarded every one of them.

def test_a_frame_is_not_named_so_onmessage_receives_it():
    """`onmessage` receives only frames of the default type "message". A frame
    carrying `event: automation.ran` goes to addEventListener and nowhere
    else — so naming them made the whole stream invisible to this client."""
    frame = cityos_main._sse_frame(
        {"seq": 7, "type": "automation.ran", "board_id": 3, "task_id": 9})
    assert "\nevent:" not in frame and not frame.startswith("event:"), frame
    # …and the type is still there, in the payload the client dispatches on
    body = [ln for ln in frame.split("\n") if ln.startswith("data: ")]
    assert len(body) == 1, frame
    assert json.loads(body[0][6:])["type"] == "automation.ran"
    # the id line stays: it is what a reconnect sends back as Last-Event-ID
    assert frame.startswith("id: 7\n"), frame
    assert frame.endswith("\n\n"), "a frame that does not end blank is never dispatched"


def test_the_browser_dispatches_on_the_type_inside_the_payload():
    """The client reads ev.type out of the JSON — which is what makes the
    `event:` line unnecessary, and is why dropping it costs nothing."""
    src = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    i = src.index("  onEvent(ev){")
    body = src[i:src.index("\n  },", i)]
    assert "ev.type" in body, body
    # and the stream is still wired to onmessage alone, which is the whole
    # reason the frame must not be named
    assert "es.onmessage=" in src
    assert "es.addEventListener(" not in src, \
        "a per-type listener was added — then the frame may be named again"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_real_eventsource_receives_this_frame(tmp_path):
    """The claim above is about a browser API, so it is checked against one
    rather than against the specification as remembered.

    Node's EventSource is the same WHATWG implementation. It serves the real
    frame this module builds, next to a named one, and reports which of them
    reached onmessage.
    """
    out = subprocess.run(["node", "-e", "console.log(typeof EventSource)"],
                         capture_output=True, text=True)
    flag = [] if out.stdout.strip() == "function" else ["--experimental-eventsource"]
    named = "id: 1\nevent: automation.ran\ndata: {\"type\":\"named\"}\n\n"
    ours = cityos_main._sse_frame({"seq": 2, "type": "automation.ran"})
    script = tmp_path / "sse.mjs"
    script.write_text("""
import http from 'http';
const NAMED = %s, OURS = %s;
const srv = http.createServer((q, s) => {
  s.writeHead(200, {'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache'});
  s.write(': hi\\n\\n'); s.write(NAMED); s.write(OURS);
});
await new Promise(r => srv.listen(0, r));
const es = new EventSource('http://127.0.0.1:' + srv.address().port + '/');
const seen = [];
es.onmessage = e => seen.push(JSON.parse(e.data).type);
await new Promise(r => setTimeout(r, 500));
es.close(); srv.close();
console.log(JSON.stringify(seen));
""" % (json.dumps(named), json.dumps(ours)), encoding="utf-8")
    r = subprocess.run(["node", *flag, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    seen = json.loads(r.stdout.strip().splitlines()[-1])
    assert seen == ["automation.ran"], (
        f"onmessage saw {seen} — the named frame must be invisible to it and "
        "ours must not be")
