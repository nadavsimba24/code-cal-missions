"""Nobody is offered the option of tagging themselves.

The menu offered it and the server threw it away — add_comment does
`mentioned.discard(user.id)` before it notifies anybody — so picking yourself
put "@your name" in the message and reached nobody. Now that a tag also sends
mail, the same nothing would be louder.

Both halves are pinned: the menu no longer offers it, and the server still
refuses it however the request was made. The typed form — "@my own name",
which never went through the menu at all — is the one a client-side change
cannot cover.
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
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


def test_the_tag_menu_does_not_offer_you_yourself():
    """Driven harness: tests/frontend/mention_self.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "mention_self.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_assignee_picker_is_untouched():
    """boardPeople feeds the אחראי picker and the people columns too, and
    putting yourself on a record is an ordinary thing to do. The filter belongs
    to the tag menu alone."""
    assert "function boardPeople(alsoInclude){" in SRC
    body = SRC.split("function boardPeople(alsoInclude){", 1)[1].split("\n}", 1)[0]
    assert "meId()" not in body, "boardPeople now hides the current user from every picker"


def test_typing_your_own_name_still_tags_nobody(client, admin_id, monkeypatch):
    """The menu is not the rule — "@my own name" typed by hand never touched
    it. The server has always dropped a self-tag and still must."""
    sent = _no_mail(monkeypatch)
    bid = client.post("/api/boards", json={"name": "לוח תיוג עצמי",
                                           "user_id": admin_id}).json()["id"]
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    sent.clear()
    r = client.post(f"/api/tasks/{tid}/comments",
                    json={"actor_id": admin_id, "content": f"@{_name(admin_id)} תזכורת",
                          "mentions": [admin_id]})
    assert r.status_code == 200, r.text

    with Session(cityos_main.engine) as db:
        c = db.query(Comment).filter(Comment.id == r.json()["id"]).first()
        assert c.mentions == [], "the comment claims to have tagged its own author"
        assert not (db.query(Notification)
                      .filter(Notification.user_id == admin_id,
                              Notification.task_id == tid,
                              Notification.type == "mention").all())
    assert sent == [], "somebody was mailed about tagging themselves"
