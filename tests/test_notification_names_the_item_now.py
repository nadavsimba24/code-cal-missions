"""ההתראה קוראת לפריט בשמו הנוכחי, לא בשם שהיה לו כשהיא נשלחה.

A notification's body is a sentence frozen at the moment it was written, and
nothing ever rewrites it. That is fine for "דנה שייך/ה אותך למשימה «X»", where
X was already a name somebody had typed — and it is the whole problem for a
rule on "כאשר נוצר פריט חדש", which fires INSIDE the creation of the row:

    שויכת למשימה «פריט חדש».

«פריט חדש» is the name the app itself puts on a new row. The item was given a
real name seconds later, and the bell went on showing the placeholder — a
notification that reads as a template nobody filled in, about an item everyone
else on the board calls something else.

So the name is no longer remembered, it is READ: /api/notifications carries
`item_title`, the title the item has right now, and the bell shows it where the
frozen sentence does not already say it.

Two rules it has to keep:

  * what somebody may not see, they are not told about either — the same rule
    the notifications already obey (see _can_see_item). An item closed to them,
    a board they are no longer on, or an item that has since been deleted has
    no live name to hand out.
  * it is an addition, not a replacement: the body is still the message.

The screen's half is tests/frontend/notification_item_name.mjs.
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from models import Notification

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "notification_item_name.mjs"


def test_the_bell_draws_the_live_name():
    """Driven harness: tests/frontend/notification_item_name.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def _board(client, admin_id, name="לוח שם חי"):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _member(client, bid, admin_id, uid, role="editor"):
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": uid,
                             "role": role}).status_code in (200, 201)


def _rule(client, bid, admin_id, uid, **kw):
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": "created_assign_person",
                          "config": {"a_person": uid}, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title="פריט חדש"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _bell(client, uid):
    r = client.get(f"/api/notifications?user_id={uid}")
    assert r.status_code == 200, r.text
    return r.json()["notifications"]


def _mine(rows, task_id):
    return next((n for n in rows if n["task_id"] == task_id), None)


# ── the name is read, not remembered ──────────────────────────────────────

def test_the_bell_carries_the_name_the_item_has_now(client, admin_id, member_id):
    """The reported case end to end: the rule fires on a row called «פריט חדש»,
    the row is then given a name, and the notification names it correctly."""
    bid = _board(client, admin_id)
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)
    tid = _item(client, bid, admin_id, "פריט חדש")
    r = client.patch(f"/api/tasks/{tid}",
                     json={"title": "שיקום כביש רמתיים", "user_id": admin_id})
    assert r.status_code == 200, r.text

    n = _mine(_bell(client, member_id), tid)
    assert n is not None, "the assignment never arrived"
    assert n["item_title"] == "שיקום כביש רמתיים", n
    # …and the body is still the message, untouched by any of this
    assert "שויכת" in n["body"], n


def test_the_frozen_body_is_not_rewritten(client, admin_id, member_id):
    """The stored row is evidence of what was sent. `item_title` is resolved on
    the way out; it must not be written back over what was said at the time."""
    bid = _board(client, admin_id, "לוח ראיה")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)
    tid = _item(client, bid, admin_id, "שם ראשון")
    client.patch(f"/api/tasks/{tid}", json={"title": "שם שני", "user_id": admin_id})
    _bell(client, member_id)
    with Session(cityos_main.engine) as db:
        row = (db.query(Notification)
                 .filter(Notification.user_id == member_id,
                         Notification.task_id == tid)
                 .order_by(Notification.id.desc()).first())
    assert "«שם ראשון»" in row.body, row.body


# ── what somebody may not see, they are not told about ────────────────────

def test_an_item_closed_to_them_hands_out_no_name(client, admin_id, member_id):
    """The item-level permission the notifications already obey. The row stays
    — it is a thing that happened to them — but the live name does not."""
    bid = _board(client, admin_id, "לוח סגור")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)
    tid = _item(client, bid, admin_id, "סודי ביותר")
    r = client.post(f"/api/tasks/{tid}/permissions",
                    json={"actor_id": admin_id, "user_id": member_id,
                          "perm": "none"})
    assert r.status_code in (200, 201), r.text
    try:
        n = _mine(_bell(client, member_id), tid)
        assert n is not None, "the notification itself must still be there"
        assert n["item_title"] is None, n
    finally:
        client.post(f"/api/tasks/{tid}/permissions",
                    json={"actor_id": admin_id, "user_id": member_id, "perm": ""})


def test_leaving_the_board_takes_the_name_with_it(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח שעזבתי")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)
    tid = _item(client, bid, admin_id, "פריט בלוח ההוא")
    assert client.delete(f"/api/boards/{bid}/members/{member_id}"
                         f"?actor_id={admin_id}").status_code == 200

    n = _mine(_bell(client, member_id), tid)
    assert n is not None
    assert n["item_title"] is None, n


def test_a_deleted_item_has_no_live_name(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח מחוק")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)
    tid = _item(client, bid, admin_id, "פריט שנמחק")
    assert client.delete(f"/api/tasks/{tid}?user_id={admin_id}").status_code == 200

    n = _mine(_bell(client, member_id), tid)
    assert n is not None
    assert n["item_title"] is None, n


# ── and a notification about no item at all is unaffected ─────────────────

def test_a_notification_with_no_item_carries_no_name(client, admin_id, member_id):
    """Being added to a board points at a board and at nothing else."""
    bid = _board(client, admin_id, "לוח הצטרפות")
    _member(client, bid, admin_id, member_id)
    rows = [n for n in _bell(client, member_id) if n["task_id"] is None]
    assert rows, "being added to a board leaves a notification"
    assert all(n["item_title"] is None for n in rows), rows


def test_one_query_for_the_items_whatever_the_list_holds(client, admin_id,
                                                         member_id):
    """The bell asks for thirty rows at a time. Resolving a name per row would
    be thirty round trips to show one list, which is why _live_item_titles
    takes the ids together — pinned by counting the statements the request
    issues, not by reading the function."""
    bid = _board(client, admin_id, "לוח הרבה")
    _member(client, bid, admin_id, member_id)
    _rule(client, bid, admin_id, member_id)
    made = [_item(client, bid, admin_id, f"פריט {i}") for i in range(6)]

    seen = []
    from sqlalchemy import event
    eng = cityos_main.engine

    def _count(conn, cursor, statement, params, context, many):
        if "FROM tasks" in statement:
            seen.append(statement)

    event.listen(eng, "before_cursor_execute", _count)
    try:
        rows = _bell(client, member_id)
    finally:
        event.remove(eng, "before_cursor_execute", _count)

    named = [n for n in rows if n["task_id"] in made]
    assert len(named) == len(made), named
    assert all(n["item_title"] for n in named), named
    assert len(seen) <= 2, seen
