"""ההתראה אומרת איזה כלל, פעם אחת, ובלי כתובת מתה.

A real notification, as received:

    שויכת למשימה
    כאשר נוצר פריט חדש · שייך את … כאשר נוצר פריט חדש · שיוך אחראי
    פריט: פריט חדש לוח: MISSIONS רעות ושלי זמן: 03/11/2026 14:20
    /?board=11&item=16102

Four separate faults in six lines.

  · The rule had a NAME and the notification did not use it. `told` fell
    through to _automation_plain_name, which is the fallback for a rule that
    was never named — the rule's own template with its blanks left as blanks,
    which is where "שייך את …" comes from. The line right above it, the one
    the item's log reads, resolved the name correctly; this one was missed.
  · The first two lines both opened with the trigger, because the unnamed
    fallback IS "trigger · action" and the line under it was "trigger · what".
    Every such notification began by saying the same thing twice.
  · The address was a bare path. _item_url read APP_BASE_URL on its own —
    a variable neither pipeline sets — instead of _app_base_url, which is the
    thing that knows what origin this deployment answers on. That also made
    {{item.url}} useless inside a notice somebody wrote.
  · And the lines were not lines: .notif-body had no white-space rule, so six
    of them arrived as one paragraph with the words run together.
"""
import pathlib

from sqlalchemy.orm import Session

import main as cityos_main
from models import Notification

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def _board(client, admin_id, name="לוח התראה"):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _member(client, bid, admin_id, uid):
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": uid,
                             "role": "editor"}).status_code in (200, 201)


def _rule(client, bid, admin_id, uid, recipe="created_notify_person", **kw):
    """A rule whose action is "send a notification".

    It was "assign somebody" here, and that moved: an assignment now arrives as
    the sentence a person was assigned to an item (see
    test_assignment_notification_says_the_assignment). The notice this system
    sends for a rule that says nothing of its own — which rule, what happened,
    the item, the board, the time — is what this file is about, and that is the
    notify action's.
    """
    cfg = {"a_person": uid}
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": recipe,
                          "config": cfg, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _last(uid, kind="automation"):
    with Session(cityos_main.engine) as db:
        return (db.query(Notification)
                  .filter(Notification.user_id == uid, Notification.type == kind)
                  .order_by(Notification.id.desc()).first())


# ── which rule, by the name somebody gave it ──────────────────────────────

def test_a_rule_with_a_name_is_called_by_it(client, admin_id, member_id):
    bid = _board(client, admin_id)
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id, name="שיוך אוטומטי לרעות")
    client.post("/api/tasks", json={"board_id": bid, "title": "פריט חדש",
                                    "user_id": admin_id})
    n = _last(member_id)
    assert n is not None, "nothing arrived"
    first = n.body.split("\n")[0]
    assert first == "שיוך אוטומטי לרעות", n.body
    # the template with its blank still a blank has no business being here
    assert "…" not in n.body, n.body


def test_a_rule_with_no_name_is_called_by_its_trigger_and_said_once(
        client, admin_id, member_id):
    """The trigger alone, and once. _automation_plain_name reads "trigger ·
    action" — "כאשר נוצר פריט חדש · שייך את …" — and that ellipsis is a value
    a notification may not quote anyway, so it is not a name. The action says
    itself in plain words on the line below."""
    bid = _board(client, admin_id, "לוח בלי שם")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)
    client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                    "user_id": admin_id})
    n = _last(member_id)
    lines = [l for l in n.body.split("\n") if l.strip()]
    assert lines[0] == "כאשר נוצר פריט חדש", lines
    assert n.body.count("כאשר נוצר פריט חדש") == 1, n.body
    # no dangling blank anywhere…
    assert "…" not in n.body, n.body
    # …and what happened is still said, in plain words
    assert lines[1] == "שליחת התראה", lines


def test_the_five_things_are_all_there(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח חמישה")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id, name="כלל")
    client.post("/api/tasks", json={"board_id": bid, "title": "הפריט שלי",
                                    "user_id": admin_id})
    n = _last(member_id)
    assert "כלל" in n.body
    assert "שליחת התראה" in n.body
    assert "פריט: הפריט שלי" in n.body, n.body
    assert "לוח: לוח חמישה" in n.body, n.body
    assert "זמן: " in n.body, n.body


# ── and no address written out in it ──────────────────────────────────────

def test_the_body_carries_no_raw_address(client, admin_id, member_id):
    """The notification IS the way to the item — the row opens it. The line
    only ever added a URL to read, and while APP_BASE_URL went unset it was
    not even that."""
    bid = _board(client, admin_id, "לוח כתובת")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id, name="כלל")
    client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                    "user_id": admin_id})
    n = _last(member_id)
    assert "?board=" not in n.body and "item=" not in n.body, n.body
    # the row still knows which item it is about, which is what opens it
    assert n.task_id and n.board_id == bid


def test_the_items_own_link_is_a_link(client, admin_id, monkeypatch):
    """{{item.url}} inside a notice somebody wrote has to be clickable from
    wherever they read it — which means an origin, not a path."""
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    bid = _board(client, admin_id, "לוח קישור")
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    with Session(cityos_main.engine) as db:
        from models import Board, Task
        b = db.query(Board).filter(Board.id == bid).first()
        t = db.query(Task).filter(Task.id == tid).first()
        url = cityos_main._item_url(b, t)
    assert url.startswith("http"), url
    assert f"board={bid}" in url and f"item={tid}" in url, url


# ── and the lines are lines ───────────────────────────────────────────────

def test_the_lines_are_shown_as_lines():
    """Six of them arrived as one paragraph with the words run together."""
    src = INDEX.read_text(encoding="utf-8")
    rule = src[src.index(".notif-body{"):]
    rule = rule[:rule.index("}") + 1]
    assert "white-space:pre-line" in rule, rule
