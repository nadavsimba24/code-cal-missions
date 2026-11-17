"""A new automation announces itself — in the bell, and by mail.

An automation is a standing instruction. The moment it is saved it acts on
everybody's items, in the board's name, with nobody pressing anything — and
the only trace of a new one used to be a line in the audit log, which is a
place people go after they already suspect something. A rule could start
moving items on a Monday and be noticed on a Thursday.

What is pinned here is who is told, when, and what they are told:

· only at birth — a rule created, never a rule edited, re-saved or renamed,
  because "נוצרה אוטומציה חדשה" arriving every time somebody fixes a typo is
  the noise that teaches people to stop reading the bell;
· the board's managers, the rule's owner and the person who wrote it, because
  the author's own copy of the sentence is the only record the product gives
  them of a thing they did to everybody else's board;
· every member of the board instead, when the box on the creation screen was
  ticked — and never otherwise, because a board of forty people does not want
  forty bells for a rule about one column;
· once per person however many of those lists they stand on;
· one sentence, complete on its own — who created which rule on which board —
  because there is nothing to press and nowhere for it to lead;
· and nothing at all on a board whose manager switched its notifications off.

The mail is the longer version of the same news and keeps its own, narrower
audience: the people who answer for the board, never the author, and never a
whole board at once — ticking a box on a form must not put forty messages in
forty inboxes. It is built before the commit and sent after it, so nothing
announces a rule that then rolled back.
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from models import Notification

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"

BODY = "{who} יצר/ה את האוטומציה «{rule}» בלוח «{board}»."


def _board(client, admin_id, name="לוח האוטומציות"):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _manager(client, bid, admin_id, uid):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": "admin"})
    assert r.status_code in (200, 201), r.text


def _member(client, bid, admin_id, uid):
    """An ordinary member — on the board, answering for nothing on it."""
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": "editor"})
    assert r.status_code in (200, 201), r.text


def _rule(client, bid, actor, **kw):
    """The simplest rule there is: a new item gets a status."""
    body = {"actor_id": actor, "recipe_id": "created_set_status",
            "config": {"a_status": "done"}, **kw}
    return client.post(f"/api/boards/{bid}/automations", json=body)


def _notices(uid, board_id=None):
    with Session(cityos_main.engine) as db:
        q = db.query(Notification).filter(
            Notification.user_id == uid,
            Notification.type == "automation_created")
        if board_id is not None:
            q = q.filter(Notification.board_id == board_id)
        return q.order_by(Notification.id.desc()).all()


class _Mails:
    """Whatever was queued for sending, without a thread in the way."""

    def __enter__(self):
        self.sent = []
        self._real = cityos_main._mail_when_committed
        cityos_main._mail_when_committed = \
            lambda db, msgs: self.sent.extend([m for m in (msgs or []) if m])
        return self

    def __exit__(self, *a):
        cityos_main._mail_when_committed = self._real
        return False


# ── who is told ───────────────────────────────────────────────────────────

def test_a_new_rule_tells_the_boards_other_managers(client, admin_id, member_id):
    bid = _board(client, admin_id, "היסעים")
    _manager(client, bid, admin_id, member_id)
    before = len(_notices(member_id, bid))

    r = _rule(client, bid, admin_id, name="סגירה אוטומטית")
    assert r.status_code == 200, r.text

    rows = _notices(member_id, bid)
    assert len(rows) == before + 1, rows
    n = rows[0]
    assert "היסעים" in n.title, n.title
    assert n.body == BODY.format(who="משה כהן", rule="סגירה אוטומטית",
                                 board="היסעים"), n.body


def test_the_one_who_wrote_it_is_told_too(client, admin_id, member_id):
    """The author is on the list on purpose.

    "יצרתי אוטומציה" is a thing done to everybody else's board, and this row
    is the author's own copy of the sentence everyone else got — the one place
    in the product that shows them what the board was told in their name."""
    bid = _board(client, admin_id, "עם הד")
    _manager(client, bid, admin_id, member_id)
    before = len(_notices(admin_id, bid))
    assert _rule(client, bid, admin_id, name="הד").status_code == 200
    rows = _notices(admin_id, bid)
    assert len(rows) == before + 1, rows
    assert rows[0].body == BODY.format(who="משה כהן", rule="הד",
                                       board="עם הד"), rows[0].body


def test_one_person_on_three_lists_is_told_once(client, admin_id):
    """The ordinary case: a manager wrote the rule and owns it.

    They reach the audience as the author, as the owner and as a manager of
    the board, and the bell is not three rows deep for it."""
    bid = _board(client, admin_id, "פעם אחת")
    before = len(_notices(admin_id, bid))
    r = _rule(client, bid, admin_id, name="כפילות", owner_id=admin_id)
    assert r.status_code == 200, r.text
    assert len(_notices(admin_id, bid)) == before + 1, _notices(admin_id, bid)


def test_the_person_a_rule_is_handed_to_at_birth_is_told(
        client, admin_id, member_id, guinea_id):
    """Rule 3 — the rule answers to its owner, so a rule born under somebody
    else's name is news to them first of all. (The server already requires an
    owner to be a manager of the board, so they would be told in any case —
    the audience names them anyway, because those are two different rules and
    this one must not quietly depend on the other.)"""
    bid = _board(client, admin_id, "בעלות")
    _manager(client, bid, admin_id, member_id)
    _manager(client, bid, admin_id, guinea_id)
    before = len(_notices(guinea_id, bid))
    r = _rule(client, bid, admin_id, owner_id=guinea_id)
    assert r.status_code == 200, r.text
    rows = _notices(guinea_id, bid)
    assert len(rows) == before + 1, rows
    assert "בעלות" in rows[0].title, rows[0].title


def test_an_ordinary_member_hears_nothing_unless_somebody_asked(
        client, admin_id, member_id):
    bid = _board(client, admin_id, "רק המנהלים")
    _member(client, bid, admin_id, member_id)
    before = len(_notices(member_id, bid))
    assert _rule(client, bid, admin_id).status_code == 200
    assert len(_notices(member_id, bid)) == before, \
        "the whole board was told without being asked"


def test_the_box_on_the_creation_screen_tells_the_whole_board(
        client, admin_id, member_id, guinea_id):
    """…and still one notification each — the manager who is also the author
    is on two of the lists and keeps one row."""
    bid = _board(client, admin_id, "כולם")
    _member(client, bid, admin_id, member_id)
    _manager(client, bid, admin_id, guinea_id)
    was = {uid: len(_notices(uid, bid))
           for uid in (admin_id, member_id, guinea_id)}

    r = _rule(client, bid, admin_id, name="לידיעת כולם",
              notify_all_members=True)
    assert r.status_code == 200, r.text

    for uid in (admin_id, member_id, guinea_id):
        assert len(_notices(uid, bid)) == was[uid] + 1, (uid, _notices(uid, bid))
    assert _notices(member_id, bid)[0].body == \
        BODY.format(who="משה כהן", rule="לידיעת כולם", board="כולם")


# ── when it is said ───────────────────────────────────────────────────────

def test_an_edit_is_not_a_birth_and_announces_nothing(
        client, admin_id, member_id):
    bid = _board(client, admin_id, "עריכה")
    _manager(client, bid, admin_id, member_id)
    r = _rule(client, bid, admin_id, name="לפני")
    assert r.status_code == 200, r.text
    after_create = len(_notices(member_id, bid))

    up = client.patch(f"/api/automations/{r.json()['id']}",
                      json={"actor_id": admin_id, "name": "אחרי"})
    assert up.status_code == 200, up.text
    assert len(_notices(member_id, bid)) == after_create, \
        "a rename announced itself as a new rule"


# ── what it says ──────────────────────────────────────────────────────────

def test_the_sentence_stands_on_its_own(client, admin_id, member_id):
    """Nothing to press, so everything to know is in the line itself: who,
    which rule, which board. A row that led somewhere could afford to say
    less; this one cannot."""
    bid = _board(client, admin_id, "משפט שלם")
    _manager(client, bid, admin_id, member_id)
    assert _rule(client, bid, admin_id, name="שם הכלל").status_code == 200
    n = _notices(member_id, bid)[0]
    for part in ("משה כהן", "שם הכלל", "משפט שלם"):
        assert part in n.body, (part, n.body)
    # it names no item, because a rule is about none of them in particular
    assert n.task_id is None, n.task_id


def test_a_rule_with_no_name_is_called_what_it_does(client, admin_id, member_id):
    """The name is optional in the builder, and «» would name nothing. The
    fallback is the rule's own sentence — what the automations list calls it."""
    bid = _board(client, admin_id, "בלי שם")
    _manager(client, bid, admin_id, member_id)
    assert _rule(client, bid, admin_id).status_code == 200
    n = _notices(member_id, bid)[0]
    assert "«»" not in n.body, n.body
    assert "פריט" in n.body and "בוצע" in n.body, n.body


# ── the mail, which keeps the narrower list ───────────────────────────────

def test_the_mail_says_what_the_rule_does_and_where(client, admin_id, member_id):
    bid = _board(client, admin_id, "דואר אוטומציות")
    _manager(client, bid, admin_id, member_id)
    with _Mails() as m:
        r = _rule(client, bid, admin_id, name="סגירה אוטומטית")
    assert r.status_code == 200, r.text
    assert len(m.sent) == 1, m.sent
    to, subject, html = m.sent[0]
    assert "דואר אוטומציות" in subject, subject
    assert "סגירה אוטומטית" in html, html
    # the sentence itself, and the board it runs on
    assert "בוצע" in html and "דואר אוטומציות" in html, html
    # …and the button lands on that board's automations, not on the board
    assert f"/#/board/{bid}/automations/{r.json()['id']}" in html, html


def test_the_mail_does_not_go_to_the_author_or_to_the_whole_board(
        client, admin_id, member_id, guinea_id):
    """The bell can afford both; an inbox cannot. The author was answered by
    the save itself, and a box ticked on a form must not put a message in
    every member's mail."""
    bid = _board(client, admin_id, "דואר מצומצם")
    _member(client, bid, admin_id, member_id)
    _manager(client, bid, admin_id, guinea_id)
    with _Mails() as m:
        assert _rule(client, bid, admin_id, notify_all_members=True) \
            .status_code == 200
    # the one other manager, and nobody else
    assert len(m.sent) == 1, m.sent
    assert m.sent[0][0] == "test.guinea@cityos.test", m.sent[0][0]


def test_a_draft_says_it_is_a_draft(client, admin_id, member_id):
    """A draft is written and does not run. Announcing it in the mail as if it
    were already acting would send somebody looking for effects it cannot
    have — and the mail is where there is room to say so."""
    bid = _board(client, admin_id, "טיוטות")
    _manager(client, bid, admin_id, member_id)
    with _Mails() as m:
        assert _rule(client, bid, admin_id, status="draft").status_code == 200
    assert "טיוטה" in m.sent[0][2], m.sent[0][2]


# ── and when the board asked for silence ──────────────────────────────────

def test_a_board_with_its_notifications_off_says_nothing(
        client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח שקט")
    _manager(client, bid, admin_id, member_id)
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id,
                              "notifications_enabled": False}).status_code == 200
    before = len(_notices(member_id, bid))
    try:
        with _Mails() as m:
            assert _rule(client, bid, admin_id).status_code == 200
        assert len(_notices(member_id, bid)) == before, "the switch was ignored"
        assert m.sent == [], m.sent
    finally:
        client.patch(f"/api/boards/{bid}",
                     json={"actor_id": admin_id, "notifications_enabled": True})


# ── the screen that asks, and the row that leads nowhere ──────────────────

def test_the_bell_row_goes_nowhere():
    """"למידע בלבד" is a thing the browser has to honour, not only the wording.

    Every other notification in the bell is a way IN to something — an item, a
    board, a conversation — and the row that handles them opens boards and
    scrolls to items. This one has no destination: the sentence is the whole
    of it. So the click handler leaves early, before any of that, and the
    person stays where they were with the row gone grey.
    """
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  async click(id,boardId,taskId){"):]
    fn = fn[:fn.index("\n  },")]
    i = fn.index("automation_created")
    assert "this.render(); return;" in fn[i:i + 120], fn[i:i + 200]
    # …and it leaves before the navigation, not after it
    assert i < fn.index("openBoard"), "the row still travels somewhere"
    assert "await Automations.open()" not in fn, fn[i:i + 300]


def test_the_creation_screen_asks_who_should_hear():
    """Driven harness: tests/frontend/automation_tells_the_board.mjs.

    Verified to fail: drop the box from buildHTML and the first three go red;
    leave notify_all_members out of the POST body and the two that watch what
    is sent do.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_tells_the_board.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
