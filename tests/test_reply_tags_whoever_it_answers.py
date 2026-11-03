"""אפשר להגיב בכל שלב בשיחה, והתגובה מתייגת את מי שעונים לו.

"הגב" was offered on a top-level message only. An answer to an answer had
nowhere to go: the conversation's second level was where it stopped being a
conversation, and the way round it was to write a new message at the bottom
and name the person by hand.

Two things, and the second is the one that matters.

The button is on every message now, and a reply to a reply joins the
thread's ROOT rather than nesting under it. The thread stays one level deep
because who is answering whom is carried by the tag and not by indentation —
the same shape _import_comment already builds, and the only one that survives
a phone screen at the fourth nesting.

And the box opens with the author of the message being answered already
tagged — typed into the text AND registered in `mentions`, so the
notification does not depend on the text surviving an edit. Without it a
reply three messages down reads as a remark to nobody, and the person it
answers is not told at all: until now a reply reached them only if they
happened to type their own name into it.

The screen is covered by the driven harness. What is pinned here is the
contract underneath it — the tag is only worth putting in the box if the
server really notifies the person it names, and really refuses to notify the
ones it must not.
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from models import AuditLog, Comment, Notification

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def _board(client, admin_id, name="לוח שיחה"):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _say(client, tid, uid, content, parent_id=None, mentions=None):
    body = {"user_id": uid, "content": content}
    if parent_id is not None:
        body["parent_id"] = parent_id
    if mentions is not None:
        body["mentions"] = mentions
    r = client.post(f"/api/tasks/{tid}/comments", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _tree(client, tid, uid):
    return client.get(f"/api/tasks/{tid}/comments?user_id={uid}").json()["comments"]


def _notes(uid, kind="mention"):
    with Session(cityos_main.engine) as db:
        return (db.query(Notification)
                  .filter(Notification.user_id == uid, Notification.type == kind)
                  .all())


# ── the thread stays one level deep ───────────────────────────────────────

def test_a_reply_to_a_reply_joins_the_thread_rather_than_nesting(
        client, admin_id, member_id):
    bid = _board(client, admin_id)
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    tid = _item(client, bid, admin_id)
    root = _say(client, tid, admin_id, "שאלה")
    first = _say(client, tid, member_id, "תשובה", parent_id=root["id"])
    # the screen files an answer to `first` under the ROOT — this is the shape
    # the server is asked for, and it is the one the importer already builds
    second = _say(client, tid, admin_id, "ועוד משהו", parent_id=root["id"])

    tree = _tree(client, tid, admin_id)
    assert len(tree) == 1, tree
    assert [r["id"] for r in tree[0]["replies"]] == [first["id"], second["id"]], tree
    # and nothing is nested under a reply
    assert all(not r.get("replies") for r in tree[0]["replies"]), tree


def test_the_audit_tells_a_reply_from_a_message(client, admin_id):
    bid = _board(client, admin_id, "לוח יומן")
    tid = _item(client, bid, admin_id)
    root = _say(client, tid, admin_id, "ראשונה")
    _say(client, tid, admin_id, "שנייה", parent_id=root["id"])
    with Session(cityos_main.engine) as db:
        fields = [r.field_name for r in db.query(AuditLog)
                  .filter(AuditLog.entity_type == "task",
                          AuditLog.entity_id == tid,
                          AuditLog.action == "comment").all()]
    assert sorted(fields) == ["comment", "reply"], fields


# ── and the tag it puts in the box really reaches the person ──────────────

def test_the_person_a_reply_answers_is_notified(client, admin_id, member_id):
    """The whole point of tagging them automatically: before this, a reply
    reached them only if they happened to type their own name into it."""
    bid = _board(client, admin_id, "לוח תיוג")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    tid = _item(client, bid, admin_id)
    root = _say(client, tid, member_id, "שאלה")
    before = len(_notes(member_id))
    name = client.get(f"/api/boards/{bid}/members?user_id={admin_id}").json()
    who = next(m["name"] for m in name["members"] if m["user_id"] == member_id)
    r = _say(client, tid, admin_id, f"@{who} תשובה",
             parent_id=root["id"], mentions=[member_id])
    assert r["mentions"] == [member_id], r
    assert len(_notes(member_id)) == before + 1


def test_the_tag_survives_the_text_being_rewritten(client, admin_id, member_id):
    """It is registered as well as typed, which is why the box's own text is
    not the only record of who was tagged."""
    bid = _board(client, admin_id, "לוח רישום")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    tid = _item(client, bid, admin_id)
    root = _say(client, tid, member_id, "שאלה")
    # the name was deleted out of the text; the id was sent beside it
    r = _say(client, tid, admin_id, "תשובה בלי שם",
             parent_id=root["id"], mentions=[member_id])
    assert r["mentions"] == [member_id], r


def test_tagging_yourself_is_discarded(client, admin_id):
    """Which is why the browser does not put your own name in the box when
    you answer your own message."""
    bid = _board(client, admin_id, "לוח עצמי")
    tid = _item(client, bid, admin_id)
    root = _say(client, tid, admin_id, "שלי")
    r = _say(client, tid, admin_id, "ועוד שלי", parent_id=root["id"],
             mentions=[admin_id])
    assert r["mentions"] == [], r


def test_somebody_off_the_board_cannot_be_tagged(client, admin_id, guinea_id):
    """And so the browser does not offer their name either: a tag in the box
    that the server will drop is a promise nobody keeps."""
    bid = _board(client, admin_id, "לוח זר")
    tid = _item(client, bid, admin_id)
    root = _say(client, tid, admin_id, "שאלה")
    before = len(_notes(guinea_id))
    r = _say(client, tid, admin_id, "תשובה", parent_id=root["id"],
             mentions=[guinea_id])
    assert r["mentions"] == [], r
    assert len(_notes(guinea_id)) == before


def test_an_imported_message_can_be_answered(client, admin_id):
    """Its author has no account here, so there is nobody to tag — but the
    message is still part of the conversation and still answerable."""
    bid = _board(client, admin_id, "לוח מיובא")
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        c = Comment(task_id=tid, user_id=None, content="יובאה",
                    origin={"source": "monday", "author": "שם מהקובץ"},
                    attachments=[], mentions=[], likes=[], seen_by=[])
        db.add(c)
        db.commit()
        cid = c.id
    r = _say(client, tid, admin_id, "תשובה", parent_id=cid)
    assert r["parent_id"] == cid, r
    tree = _tree(client, tid, admin_id)
    node = next(x for x in tree if x["id"] == cid)
    assert [y["id"] for y in node["replies"]] == [r["id"]], tree


# ── the browser's half ────────────────────────────────────────────────────

def test_every_message_offers_a_reply():
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  commentHTML(c,isReply){"):]
    fn = fn[:fn.index("\n  },")]
    assert "canComment()?`<button onclick=\"Chat.startReply(" in fn, fn
    assert "!isReply&&canComment()" not in fn, "the second level is gated again"


def test_a_reply_to_a_reply_is_filed_under_the_root():
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  startReply(id,name){"):]
    fn = fn[:fn.index("\n  },")]
    assert "this.replyTo=(c&&c.parent_id)||id;" in fn, fn
    assert "this.tagReplied(c,ta);" in fn, fn


def test_the_tag_is_registered_and_not_only_typed():
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  tagReplied(c,ta){"):]
    fn = fn[:fn.index("\n  },")]
    assert "this.mentions.push(uid)" in fn, fn
    # the three it must not tag
    assert "if(!uid||uid===meId())return;" in fn, fn
    assert "this.mentionPeople().find(x=>x.id===uid)" in fn, fn


def test_the_whole_thing_in_the_browser(client, admin_id):
    """Driven harness: tests/frontend/reply_tags_whoever_it_answers.mjs.

    Verified to fail: put the !isReply gate back and two cases go red; drop
    tagReplied and six more do.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "reply_tags_whoever_it_answers.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
