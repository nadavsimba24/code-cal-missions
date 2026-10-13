"""A like has to reach the person who wrote the thing being liked.

Everything else in a conversation spoke: a mention notifies, a new message
raises the item's unread count. A thumbs-up did neither — the author of the
comment had no way to learn it had happened unless they went back and counted
the likes themselves.

In-app only, and that is a decision rather than an omission: the mail this
system sends is an invitation to a board or a workspace, and a thumbs-up is not
that. _notify writes a notification row and nothing else, so these tests also
pin that nothing is mailed.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Comment, Notification


def _mk_board(client, admin_id, invite=None, name="לוח שיחה"):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    if invite is not None:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": invite, "role": "editor"})
    return bid


def _mk_item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _comment(client, tid, author_id, text="הערה"):
    return client.post(f"/api/tasks/{tid}/comments",
                       json={"actor_id": author_id, "content": text}).json()["id"]


def _likes(user_id, task_id):
    """Scoped to the item: the suite shares one database, so counting every
    like notification this user ever got would count the other tests'."""
    with Session(cityos_main.engine) as db:
        return (db.query(Notification)
                  .filter(Notification.user_id == user_id,
                          Notification.type == "comment_like",
                          Notification.task_id == task_id).all())


def _no_mail(monkeypatch):
    sent = []
    monkeypatch.setattr(cityos_main, "_send_email",
                        lambda to, subject, html: sent.append(to) or True)
    return sent


def test_liking_a_comment_notifies_its_author(client, admin_id, guinea_id, monkeypatch):
    mail = _no_mail(monkeypatch)
    bid = _mk_board(client, admin_id, invite=guinea_id)
    tid = _mk_item(client, bid, admin_id, "מדרכה שבורה")
    cid = _comment(client, tid, admin_id, "טופל")
    mail.clear()

    r = client.post(f"/api/comments/{cid}/like", json={"actor_id": guinea_id})
    assert r.status_code == 200
    assert guinea_id in r.json()["likes"]

    got = _likes(admin_id, tid)
    assert len(got) == 1, got
    n = got[0]
    assert "לייק" in n.title
    assert "מדרכה שבורה" in n.body        # which item, in the author's words
    assert n.board_id == bid and n.task_id == tid   # one click back to the place
    assert n.is_read is False
    # no mail, by design
    assert mail == [], mail


def test_nobody_is_notified_of_their_own_like(client, admin_id, monkeypatch):
    _no_mail(monkeypatch)
    bid = _mk_board(client, admin_id)
    tid = _mk_item(client, bid, admin_id)
    cid = _comment(client, tid, admin_id)
    client.post(f"/api/comments/{cid}/like", json={"actor_id": admin_id})
    assert _likes(admin_id, tid) == []


def test_taking_a_like_back_is_not_news(client, admin_id, guinea_id, monkeypatch):
    _no_mail(monkeypatch)
    bid = _mk_board(client, admin_id, invite=guinea_id)
    tid = _mk_item(client, bid, admin_id)
    cid = _comment(client, tid, admin_id)
    client.post(f"/api/comments/{cid}/like", json={"actor_id": guinea_id})   # on
    before = len(_likes(admin_id, tid))
    client.post(f"/api/comments/{cid}/like", json={"actor_id": guinea_id})   # off
    assert len(_likes(admin_id, tid)) == before


def test_fidgeting_with_the_button_is_one_piece_of_news(client, admin_id, guinea_id, monkeypatch):
    """Like, unlike, like again is one person changing their mind, and while the
    first notification is still unread it stands for all of it."""
    _no_mail(monkeypatch)
    bid = _mk_board(client, admin_id, invite=guinea_id)
    tid = _mk_item(client, bid, admin_id)
    cid = _comment(client, tid, admin_id)
    for _ in range(3):
        client.post(f"/api/comments/{cid}/like", json={"actor_id": guinea_id})   # on
        client.post(f"/api/comments/{cid}/like", json={"actor_id": guinea_id})   # off
    client.post(f"/api/comments/{cid}/like", json={"actor_id": guinea_id})
    assert len(_likes(admin_id, tid)) == 1

    # ...but once it has been read, the next like is news again
    rows = _likes(admin_id, tid)
    client.post(f"/api/notifications/{rows[0].id}/read", json={"actor_id": admin_id})
    client.post(f"/api/comments/{cid}/like", json={"actor_id": guinea_id})   # off
    client.post(f"/api/comments/{cid}/like", json={"actor_id": guinea_id})   # on
    assert len(_likes(admin_id, tid)) == 2


def test_two_people_liking_are_two_notifications(client, admin_id, guinea_id, monkeypatch):
    """The dedupe is per liker — it must not swallow somebody else's like."""
    _no_mail(monkeypatch)
    bid = _mk_board(client, admin_id, invite=guinea_id)
    users = client.get(f"/api/users?user_id={admin_id}").json()
    users = users if isinstance(users, list) else users["users"]
    # not the automation identity: it is not a person and may not act
    third = next((u["id"] for u in users
                  if u["id"] not in (admin_id, guinea_id)
                  and not str(u.get("email") or "").endswith("@system.local")), None)
    if third is None:
        return                      # a two-person database has nothing to prove
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": third, "role": "editor"})
    tid = _mk_item(client, bid, admin_id)
    cid = _comment(client, tid, admin_id)
    client.post(f"/api/comments/{cid}/like", json={"actor_id": guinea_id})
    client.post(f"/api/comments/{cid}/like", json={"actor_id": third})
    assert len(_likes(admin_id, tid)) == 2


def test_a_board_with_notifications_off_stays_quiet(client, admin_id, guinea_id, monkeypatch):
    """The board admin's switch covers this like every other notification."""
    _no_mail(monkeypatch)
    bid = _mk_board(client, admin_id, invite=guinea_id)
    client.patch(f"/api/boards/{bid}?user_id={admin_id}",
                 json={"notifications_enabled": False})
    tid = _mk_item(client, bid, admin_id)
    cid = _comment(client, tid, admin_id)
    client.post(f"/api/comments/{cid}/like", json={"actor_id": guinea_id})
    assert _likes(admin_id, tid) == []


def test_an_imported_comment_with_no_account_behind_it_notifies_nobody(client, admin_id, guinea_id, monkeypatch):
    """An imported conversation can carry messages whose author has no user
    here; `user_id` is empty on those by design."""
    _no_mail(monkeypatch)
    bid = _mk_board(client, admin_id, invite=guinea_id)
    tid = _mk_item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        c = Comment(task_id=tid, user_id=None, content="מ-Monday", mentions=[],
                    likes=[], seen_by=[], origin={"source": "monday", "author": "דנה"})
        db.add(c); db.commit(); db.refresh(c)
        cid = c.id
    r = client.post(f"/api/comments/{cid}/like", json={"actor_id": guinea_id})
    assert r.status_code == 200
    with Session(cityos_main.engine) as db:
        assert db.query(Notification).filter(
            Notification.type == "comment_like", Notification.task_id == tid).count() == 0
