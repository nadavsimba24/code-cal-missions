"""Server→client event bus — the doorbell for live updates.

An event says *that* something changed, never *what* it now is:

    {"seq": 41, "type": "task.changed", "board_id": 7, "task_id": 42, "actor_id": 3}

The client refetches through the normal REST endpoint, so per-item and
per-column permissions are enforced in exactly one place and the stream can
never hand a user a field they may not see.

Two things here are easy to get wrong and are the reason this is its own module:

* `publish()` is called from ordinary sync request handlers, which FastAPI runs
  on a worker thread. `asyncio.Queue` is not thread-safe, so publishing hops
  onto the event loop with `call_soon_threadsafe` instead of touching queues
  directly.
* A subscriber that cannot keep up must not grow memory without bound. Queues
  are small; on overflow the backlog is dropped and replaced by a single
  "resync" instruction, which is cheap and always correct.
"""
import asyncio
import itertools
import os
from typing import Optional


def _flag(name, default="1"):
    return (os.getenv(name, default) or "").strip().lower() not in ("0", "false", "no", "off")


# Live updates can be switched off without a redeploy (env var on the container).
EVENTS_ENABLED = _flag("CITYOS_EVENTS")
# Per-subscriber backlog. Small on purpose: falling behind should trigger a
# resync quickly rather than accumulate stale work.
QUEUE_MAX = int(os.getenv("CITYOS_EVENTS_QUEUE", "100"))
# Comment frame keeping proxies from closing an idle stream (Container Apps
# drops idle connections after a few minutes).
HEARTBEAT_SECONDS = int(os.getenv("CITYOS_EVENTS_HEARTBEAT", "20"))


class Bus:
    def __init__(self):
        self._subs: set[asyncio.Queue] = set()
        self._seq = itertools.count(1)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop):
        """Remember the serving loop — publish() runs on worker threads."""
        self._loop = loop

    @property
    def subscribers(self):
        return len(self._subs)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        self._subs.add(q)
        return q

    def unsubscribe(self, q):
        self._subs.discard(q)

    def publish(self, type: str, board_id=None, task_id=None, actor_id=None, **extra):
        """Announce a change. Safe to call from a sync endpoint, and never raises —
        a failure to notify must not fail the write that succeeded."""
        if not EVENTS_ENABLED:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        ev = {"seq": next(self._seq), "type": type,
              "board_id": board_id, "task_id": task_id, "actor_id": actor_id}
        ev.update(extra)
        try:
            loop.call_soon_threadsafe(self._fanout, ev)
        except RuntimeError:
            pass          # loop shutting down — nothing to notify

    def _fanout(self, ev):
        """Runs on the event loop, so touching the queues here is safe."""
        for q in list(self._subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                self._drop_and_resync(q, ev)

    @staticmethod
    def _drop_and_resync(q, ev):
        """This client is behind. Throw the backlog away and tell it to start
        over — one message replaces an unbounded queue of stale ones."""
        try:
            while True:
                q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            q.put_nowait({"seq": ev.get("seq"), "type": "resync",
                          "board_id": None, "task_id": None, "actor_id": None})
        except asyncio.QueueFull:
            pass


bus = Bus()
