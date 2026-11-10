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

## 10/11/2026 — the same complaint again, about what was left

That round left two pieces of the template standing, and they were what she
read next:

    שויכת למשימה «פריט חדש».
    לוח: MISSIONS רעות ושלי
    שיוך אוטומטי · כאשר נוצר פריט חדש
    זמן: 10/11/2026 09:09

  · «פריט חדש» is not a name. A rule on "כאשר נוצר פריט חדש" fires INSIDE the
    creation, while the row still carries the name the app gives a new item —
    and a body is frozen when it is written, so it went on saying «פריט חדש»
    after the item had been given a real name. The name is not quoted at all
    in that case now, and the bell reads the item's live name off the board
    instead (tests/test_notification_names_the_item_now.py).
  · "· כאשר נוצר פריט חדש" is the rule's trigger, in the rule's own words,
    about a thing the reader cannot see. A named rule still names itself; an
    unnamed one says only that a rule did this and not a colleague.
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


def test_an_unnamed_rule_says_a_rule_did_it_and_stops_there(client, admin_id,
                                                            member_id):
    """Without a name there is nothing to quote. "שיוך אוטומטי" is the whole of
    what the reader needs — somebody did not choose them by hand.

    The trigger used to be added after it, and that is the line she read as the
    template: it describes the RULE, in the words the rule was built from, and
    a reader who cannot open the automations screen can do nothing with it."""
    bid = _board(client, admin_id, "לוח אנונימי")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)
    _fire(client, bid, admin_id, "פריט")
    n = _last_assign(member_id)
    assert "שיוך אוטומטי" in n.body, n.body
    assert "כאשר נוצר פריט חדש" not in n.body, n.body
    assert "·" not in n.body, n.body


# ── and a row that has not been named is not quoted as if it had ──────────

def test_a_brand_new_item_is_not_quoted_by_its_placeholder(client, admin_id,
                                                           member_id):
    """The case the rule actually fires in: "כאשר נוצר פריט חדש" runs inside
    the creation, so the only name the item has is the one the app typed into
    it. «פריט חדש» in quotation marks reads as a blank nobody filled in."""
    bid = _board(client, admin_id, "לוח פריט חדש")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)
    _fire(client, bid, admin_id, "פריט חדש")        # exactly what the button sends
    n = _last_assign(member_id)
    assert "«פריט חדש»" not in n.body, n.body
    assert n.body.split("\n")[0] == "שויכת לפריט חדש, שטרם ניתן לו שם.", n.body
    assert "לוח: לוח פריט חדש" in n.body, n.body


def test_an_item_someone_named_is_still_quoted(client, admin_id, member_id):
    """The placeholder is the exception, not the rule — a name a person typed
    is the most useful thing the notification can carry."""
    bid = _board(client, admin_id, "לוח שם אמיתי")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)
    _fire(client, bid, admin_id, "תיקון מדרכה ברחוב הרצל")
    n = _last_assign(member_id)
    assert "«תיקון מדרכה ברחוב הרצל»" in n.body, n.body


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
