"""כשאוטומציה פועלת — הלוח מתרענן, גם אצל מי שהפעיל אותה.

The engine already recorded every run durably: _emit writes an
"automation.ran" row into the outbox inside the same transaction as
everything the rule did, deliberately, because an event sent before the
commit announces something that may yet be rolled back.

The other half of that bargain was kept by nobody. _drain_outbox ran when
somebody opened the board, or its automations screen, and in no other place
— so the row sat in the table until the next board read. And the next board
read was the person pressing F5 to find out whether the automation had done
anything. From the outside that is a rule that does nothing, and the first
thing anyone does about it is run it again.

Two halves, and both were needed:

  · the server sends it the moment the transaction lands, armed on the
    session's own after_commit rather than from the twenty-odd places a rule
    can fire — the commit is the only moment this is safe, and the session
    is the only thing that knows when that is;
  · the browser treats it as a reason to re-read the BOARD, and does not
    discard it as "my own edit". The person whose edit set the rule off is
    the one client that was never told, and is the one who most needs to be:
    the rule wrote things they did not type.
"""
import pathlib

from sqlalchemy.orm import Session

import main as cityos_main
from models import EventOutbox

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def _board(client, admin_id, name="לוח ריענון"):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _rule(client, bid, admin_id, recipe_id="created_set_priority", config=None):
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": recipe_id,
                          "config": config or {"a_priority": "high"}})
    assert r.status_code == 200, r.text
    return r.json()


def _outbox(bid):
    with Session(cityos_main.engine) as db:
        return (db.query(EventOutbox).filter(EventOutbox.board_id == bid)
                  .order_by(EventOutbox.id).all())


class _Spy:
    """Everything the bus was told, while it was told it."""

    def __enter__(self):
        self.sent = []
        self._real = cityos_main.bus.publish
        cityos_main.bus.publish = lambda kind, **kw: self.sent.append((kind, kw))
        return self

    def __exit__(self, *a):
        cityos_main.bus.publish = self._real
        return False

    def kinds(self):
        return [k for k, _ in self.sent]


# ── the server tells them, without being asked again ───────────────────────

def test_a_rule_that_ran_is_announced_without_anybody_rereading_the_board(
        client, admin_id):
    """The whole of it. Nothing here opens the board after the write."""
    bid = _board(client, admin_id)
    _rule(client, bid, admin_id)
    with _Spy() as spy:
        tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                              "user_id": admin_id}).json()["id"]
    assert "automation.ran" in spy.kinds(), spy.kinds()
    ran = next(kw for k, kw in spy.sent if k == "automation.ran")
    assert ran["board_id"] == bid and ran["task_id"] == tid, ran
    # …and the row is marked, so the next drain does not send it again
    assert all(r.sent_at is not None for r in _outbox(bid)), \
        [(r.id, r.kind, r.sent_at) for r in _outbox(bid)]


def test_it_is_announced_after_the_commit_and_not_before(client, admin_id):
    """An event that goes out first announces something that may yet be
    rolled back — which is the reason the row is written inside the
    transaction in the first place."""
    bid = _board(client, admin_id, "לוח סדר")
    _rule(client, bid, admin_id, "status_set_priority",
          {"t_status": "done", "a_priority": "critical"})
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    seen = []
    real = cityos_main.bus.publish

    def spy(kind, **kw):
        if kind == "automation.ran":
            # by the time it is announced, the write it announces is readable
            # from a session of its own — which is only true after the commit
            with Session(cityos_main.engine) as db:
                from models import Task
                t = db.query(Task).filter(Task.id == kw.get("task_id")).first()
                seen.append(t.priority.value if t and t.priority else None)
        return real(kind, **kw)

    cityos_main.bus.publish = spy
    try:
        r = client.patch(f"/api/tasks/{tid}",
                         json={"user_id": admin_id, "status": "done"})
        assert r.status_code == 200, r.text
    finally:
        cityos_main.bus.publish = real
    assert seen == ["critical"], seen


def test_a_rule_that_did_not_fire_announces_nothing(client, admin_id):
    """A board with no rule on it must not start paying for a drain on every
    write — the listener is armed by the event, not by the request."""
    bid = _board(client, admin_id, "לוח בלי כללים")
    with _Spy() as spy:
        client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                        "user_id": admin_id})
    assert "automation.ran" not in spy.kinds(), spy.kinds()


def test_a_second_write_in_the_same_session_is_announced_too(client, admin_id):
    """The listener is once=True and re-arms itself; a session that commits
    twice must not go quiet after the first."""
    bid = _board(client, admin_id, "לוח פעמיים")
    _rule(client, bid, admin_id)
    with _Spy() as spy:
        client.post("/api/tasks", json={"board_id": bid, "title": "א",
                                        "user_id": admin_id})
        client.post("/api/tasks", json={"board_id": bid, "title": "ב",
                                        "user_id": admin_id})
    assert spy.kinds().count("automation.ran") == 2, spy.kinds()


def test_a_drain_that_blows_up_cannot_fail_the_write(client, admin_id):
    """By the time the drain runs the work is already saved, so this must
    swallow whatever it meets. The route's own bus.publish is a separate
    question and is left exactly as it was — only the drain is new here."""
    bid = _board(client, admin_id, "לוח פיצוץ")
    _rule(client, bid, admin_id)
    real = cityos_main.bus.publish

    def boom(kind, **kw):
        if kind == "automation.ran":
            raise RuntimeError("the bus is down")
        return real(kind, **kw)

    cityos_main.bus.publish = boom
    try:
        r = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                            "user_id": admin_id})
        assert r.status_code == 200, r.text
    finally:
        cityos_main.bus.publish = real
    # and the row is left unsent rather than marked — at-least-once, so the
    # next drain tries again instead of losing it
    rows = [r for r in _outbox(bid) if r.kind == "automation.ran"]
    assert rows and all(r.sent_at is None for r in rows), \
        [(r.id, r.sent_at, r.attempts) for r in rows]


# ── and the browser acts on it ─────────────────────────────────────────────

def test_the_person_who_set_the_rule_off_is_not_filtered_out():
    """They are the one client that was never told, and the one who most
    needs to be: the rule wrote what they did not type."""
    src = INDEX.read_text(encoding="utf-8")
    live = src[src.index("const Live = {"):]
    fn = live[live.index("  onEvent(ev){"):]
    fn = fn[:fn.index("\n  },")]
    assert "if(ev.actor_id===meId() && ev.type!=='automation.ran')return;" in fn, fn


def test_a_rule_that_ran_re_reads_the_whole_board():
    """The event names the item the rule fired ON, which is not the list of
    what it then wrote — an action can assign a person, move the item to
    another group, add a sub-item, or set a column on an item elsewhere."""
    src = INDEX.read_text(encoding="utf-8")
    live = src[src.index("const Live = {"):]
    fn = live[live.index("  async apply(){"):]
    fn = fn[:fn.index("\n  },")]
    assert "if(ev.type==='automation.ran'){ whole=true; break; }" in fn, fn
    # and `whole` is what reloads the board
    assert "if(whole){ await this.refreshBoard(); return; }" in fn, fn
