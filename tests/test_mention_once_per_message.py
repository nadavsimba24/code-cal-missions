"""A person can be tagged once in a message, and the menu stops offering them.

The tag menu went on offering somebody already tagged in the composer, so one
message could carry "@דנה לוי" three times. The repeats were never a second
notification — the server builds a SET of the tags, from the explicit array and
from every "@Name" it finds in the text — so what they added was a name in the
text reading as a fresh call on somebody's attention that nobody would ever
receive.

Both halves are pinned. The menu no longer offers a name already in the box,
and since 2026-11-19 a message that tags the same person twice is REFUSED,
by the composer before it sends and by the server for any client. A name
typed out in full or pasted in never goes through the menu, so the menu
alone could not keep the rule. A single tag still notifies once, however
many times the explicit `mentions` array repeats the id.
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from conftest import join_primary_env
from models import Comment, Notification, User

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _no_mail(monkeypatch):
    sent = []
    monkeypatch.setattr(cityos_main, "_send_email",
                        lambda to, subject, html: sent.append(to) or True)
    return sent


def _name(uid):
    with Session(cityos_main.engine) as db:
        return db.query(User.name).filter(User.id == uid).scalar()


def test_the_tag_menu_offers_a_person_once_per_message():
    """Driven harness: tests/frontend/mention_once_per_message.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "mention_once_per_message.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_filter_is_not_applied_to_mentionPeople():
    """mentionSettled asks mentionPeople whether a tag is finished. Filtering
    the already-tagged out of THAT list would make a finished tag look
    unfinished — the menu would reopen over a completed name and take Enter
    with it, which is the bug the mentionCtx comment was written for."""
    assert "mentionPeople(){" in SRC
    body = SRC.split("mentionPeople(){", 1)[1].split("},", 1)[0]
    assert "taggedAlready" not in body, \
        "mentionPeople now hides the already-tagged, which breaks mentionSettled"


EMAIL = "dana.once@cityos.test"


def _colleague(client, admin_id):
    """A real, active user who may be invited to a board. Reused across runs
    rather than created afresh — the suite has to be able to run twice."""
    for u in client.get("/api/users").json():
        if u.get("email") == EMAIL:
            uid = u["id"]
            break
    else:
        r = client.post("/api/users", json={"name": "דנה לוי", "email": EMAIL,
                                            "actor_id": admin_id})
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
    join_primary_env(client, uid)
    return uid


def _board_with(client, admin_id, oid, name):
    bid = client.post("/api/boards", json={"name": name,
                                           "user_id": admin_id}).json()["id"]
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    r = client.post(f"/api/boards/{bid}/members",
                    json={"user_id": oid, "role": "editor", "actor_id": admin_id})
    assert r.status_code == 200, r.text
    return bid, tid


def test_a_message_that_tags_the_same_person_twice_is_refused(client, admin_id, monkeypatch):
    """The menu is not the rule. Somebody can still type the same name twice,
    or paste it, and the server must refuse the message and say who."""
    _no_mail(monkeypatch)
    oid = _colleague(client, admin_id)
    bid, tid = _board_with(client, admin_id, oid, "לוח תיוג כפול")
    try:
        name = _name(oid)
        r = client.post(f"/api/tasks/{tid}/comments",
                        json={"actor_id": admin_id,
                              "content": f"@{name} תראי, @{name} שוב"})
        assert r.status_code == 400, r.text
        assert name in r.json()["detail"], r.json()
        with Session(cityos_main.engine) as db:
            assert db.query(Comment).filter(Comment.task_id == tid).count() == 0, \
                "the refused message was saved anyway"
            assert (db.query(Notification)
                      .filter(Notification.user_id == oid, Notification.task_id == tid)
                      .count()) == 0, "the refused message still notified"
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={admin_id}")


def test_an_edit_that_adds_a_second_tag_is_refused_and_changes_nothing(client, admin_id, monkeypatch):
    _no_mail(monkeypatch)
    oid = _colleague(client, admin_id)
    bid, tid = _board_with(client, admin_id, oid, "לוח עריכת תיוג כפול")
    try:
        name = _name(oid)
        r = client.post(f"/api/tasks/{tid}/comments",
                        json={"actor_id": admin_id, "content": f"@{name} שלום"})
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        r = client.patch(f"/api/comments/{cid}",
                         json={"actor_id": admin_id,
                               "content": f"@{name} שלום, ושוב @{name}"})
        assert r.status_code == 400, r.text
        with Session(cityos_main.engine) as db:
            assert db.query(Comment).filter(Comment.id == cid).first().content \
                == f"@{name} שלום", "a refused edit still rewrote the message"
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={admin_id}")


def test_one_tag_notifies_once_even_when_the_id_is_repeated(client, admin_id, monkeypatch):
    """The explicit array is not text anybody reads, so a repeated id there is
    not refused. It is folded into the one tag it is."""
    sent = _no_mail(monkeypatch)
    oid = _colleague(client, admin_id)
    bid, tid = _board_with(client, admin_id, oid, "לוח תיוג יחיד")
    try:
        sent.clear()
        name = _name(oid)
        r = client.post(f"/api/tasks/{tid}/comments",
                        json={"actor_id": admin_id, "content": f"@{name} תראי",
                              "mentions": [oid, oid]})
        assert r.status_code == 200, r.text
        with Session(cityos_main.engine) as db:
            c = db.query(Comment).filter(Comment.id == r.json()["id"]).first()
            assert c.mentions == [oid], f"the tag was stored {len(c.mentions)} times"
            notes = (db.query(Notification)
                       .filter(Notification.user_id == oid,
                               Notification.task_id == tid,
                               Notification.type == "mention").all())
            assert len(notes) == 1, f"one tag sent {len(notes)} notifications"
        assert len(sent) <= 1, f"one message mailed the same person {len(sent)} times"
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={admin_id}")


def test_two_people_whose_names_share_a_start_can_each_be_tagged_once(client, admin_id):
    """"@שלי פיינברג" is one tag of the longer name, not also a tag of "שלי".
    Counting substrings would refuse a perfectly ordinary message."""
    ids = []
    for nm, em in (("בודקת קידומת", "prefix.short@cityos.test"),
                   ("בודקת קידומת ארוכה", "prefix.long@cityos.test")):
        hit = [u for u in client.get("/api/users").json() if u.get("email") == em]
        if hit:
            ids.append(hit[0]["id"])
        else:
            r = client.post("/api/users", json={"name": nm, "email": em,
                                                "actor_id": admin_id})
            assert r.status_code == 200, r.text
            ids.append(r.json()["id"])
    with Session(cityos_main.engine) as db:
        assert cityos_main._tagged_twice(
            db, "@בודקת קידומת ארוכה ו@בודקת קידומת שלום") == []
        assert cityos_main._tagged_twice(
            db, "@בודקת קידומת ארוכה ו@בודקת קידומת ארוכה") == ["בודקת קידומת ארוכה"]
