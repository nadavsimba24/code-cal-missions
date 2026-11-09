"""התראת שיוך אומרת לאיזו משימה שויכת — לא את הגדרת הכלל.

The same news arrived as two different messages, and which one you got
depended on who did the assigning.

By hand it is a sentence that names the item:

    שויכת למשימה
    דנה שייך/ה אותך למשימה 'הפריט שלי'.

From an automation it was the rule's own description — trigger, action, item,
board, time — reported as:

    שויכת למשימה
    כאשר נוצר פריט חדש
    שיוך אחראי
    פריט: פריט חדש
    לוח: MISSIONS רעות ושלי
    זמן: 09/11/2026 10:34

"שאני רואה את התבנית במקום לראות את תוכן ההתראה עצמה" — and that is exactly
what it is: four lines of rule definition before the reader learns anything
the title did not already say. _notice_body answers "which rule fired", which
is the right answer for "אוטומציה הופעלה" (pinned in
test_notification_says_which_rule) and the wrong one here.

So the item leads, the way it does by hand, and which rule did it stays on a
line of its own below — an assignment nobody can account for is the thing that
line was added to prevent.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import Notification


def _board(client, admin_id, name="לוח שיוך"):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _member(client, bid, admin_id, uid):
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": uid,
                             "role": "editor"}).status_code in (200, 201)


def _rule(client, bid, admin_id, uid, **kw):
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": "created_assign_person",
                          "config": {"a_person": uid}, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _last_assign(uid):
    with Session(cityos_main.engine) as db:
        return (db.query(Notification)
                  .filter(Notification.user_id == uid, Notification.type == "assign")
                  .order_by(Notification.id.desc()).first())


def _fire(client, bid, admin_id, title):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


# ── the item leads ────────────────────────────────────────────────────────

def test_the_first_line_names_the_item(client, admin_id, member_id):
    bid = _board(client, admin_id)
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id, name="שיוך אוטומטי לרעות")
    _fire(client, bid, admin_id, "הפריט שלי")
    n = _last_assign(member_id)
    assert n is not None, "nothing arrived"
    first = n.body.split("\n")[0]
    assert "הפריט שלי" in first, n.body
    assert first.startswith("שויכת למשימה"), n.body


def test_the_rule_definition_is_not_the_message(client, admin_id, member_id):
    """The two lines that read as a template: the trigger on its own, and the
    action named as a category. Neither is news about an item."""
    bid = _board(client, admin_id, "לוח בלי שם")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)           # unnamed, as reported
    _fire(client, bid, admin_id, "פריט חדש")
    n = _last_assign(member_id)
    lines = [l for l in n.body.split("\n") if l.strip()]
    assert lines[0] != "כאשר נוצר פריט חדש", n.body
    assert "שיוך אחראי" not in n.body, n.body
    assert "פריט: " not in n.body, n.body           # the item is in the sentence
    assert "…" not in n.body, n.body


# ── and which rule did it is still accounted for ──────────────────────────

def test_a_named_rule_is_still_named(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח שם")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id, name="שיוך אוטומטי לרעות")
    _fire(client, bid, admin_id, "פריט")
    n = _last_assign(member_id)
    assert "שיוך אוטומטי לרעות" in n.body, n.body
    assert "לוח: לוח שם" in n.body, n.body
    assert "זמן: " in n.body, n.body


def test_an_unnamed_rule_is_still_an_automatic_assignment(client, admin_id,
                                                          member_id):
    """Without a name there is nothing to quote, so the reader is told at
    least that nobody chose them by hand, and what moment did."""
    bid = _board(client, admin_id, "לוח אנונימי")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)
    _fire(client, bid, admin_id, "פריט")
    n = _last_assign(member_id)
    assert "שיוך אוטומטי" in n.body, n.body
    assert "כאשר נוצר פריט חדש" in n.body, n.body


# ── a hand-made assignment is untouched ───────────────────────────────────

def test_assigning_by_hand_still_names_who_did_it(client, admin_id, member_id):
    """The path this one was made to match — it must not have moved."""
    bid = _board(client, admin_id, "לוח ידני")
    _member(client, bid, admin_id, member_id)
    tid = _fire(client, bid, admin_id, "פריט ידני")
    r = client.post(f"/api/tasks/{tid}/assignees",
                    json={"user_id": member_id, "actor_id": admin_id})
    assert r.status_code in (200, 201), r.text
    n = _last_assign(member_id)
    assert "פריט ידני" in n.body, n.body
    assert "שיוך אוטומטי" not in n.body, n.body
