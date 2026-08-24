"""Tagging is limited to people invited to the board — every route in.

The people-column rule is covered in test_people_membership.py. This file covers
the paths that bypass a picker entirely: a comment, an "@Name" typed straight
into the text, an edit made after the fact, and a stored automation whose target
was removed from the board since the rule was written.
"""
from conftest import TestClient, ADMIN_ID  # noqa: F401


def _outsider(client, admin_id, email="outsider.mention@cityos.test"):
    """A real, active user who is NOT a member of board 1."""
    for u in client.get("/api/users").json():
        if u.get("email") == email:
            uid = u["id"]
            break
    else:
        uid = client.post("/api/users", json={"actor_id": admin_id, "name": "זר מהמערכת",
                                              "email": email, "role": "member"}).json()["id"]
    # make sure a previous run did not leave them enrolled
    client.delete(f"/api/boards/1/members/{uid}?actor_id={admin_id}")
    return uid


def _task(client, admin_id, title="פריט לבדיקת תיוג"):
    return client.post("/api/tasks", json={"actor_id": admin_id, "board_id": 1,
                                           "title": title}).json()["id"]


def _unread_for(client, uid):
    """Mention notifications this user holds. The endpoint returns
    {notifications: [...], unread_count: n}, not a bare list."""
    r = client.get(f"/api/notifications?user_id={uid}")
    if r.status_code != 200:
        return []
    return [n for n in (r.json().get("notifications") or []) if n.get("type") == "mention"]


def test_comment_cannot_tag_a_non_member(client, admin_id):
    out = _outsider(client, admin_id)
    tid = _task(client, admin_id)
    before = len(_unread_for(client, out))
    r = client.post(f"/api/tasks/{tid}/comments",
                    json={"actor_id": admin_id, "content": "שלום", "mentions": [out]})
    assert r.status_code == 200
    assert out not in (r.json().get("mentions") or []), "a non-member was stored as tagged"
    assert len(_unread_for(client, out)) == before, "a non-member was notified"


def test_typing_at_name_does_not_tag_a_non_member(client, admin_id):
    """The picker can be bypassed by typing — the server still has to hold."""
    out = _outsider(client, admin_id, "outsider.typed@cityos.test")
    name = next(u["name"] for u in client.get("/api/users").json() if u["id"] == out)
    tid = _task(client, admin_id)
    before = len(_unread_for(client, out))
    r = client.post(f"/api/tasks/{tid}/comments",
                    json={"actor_id": admin_id, "content": f"היי @{name} תסתכל"})
    assert r.status_code == 200
    assert len(_unread_for(client, out)) == before


def test_comment_can_tag_a_member(client, admin_id, member_id):
    tid = _task(client, admin_id)
    r = client.post(f"/api/tasks/{tid}/comments",
                    json={"actor_id": admin_id, "content": "שלום", "mentions": [member_id]})
    assert r.status_code == 200
    assert member_id in (r.json().get("mentions") or [])


def test_editing_a_comment_cannot_add_a_non_member(client, admin_id, member_id):
    out = _outsider(client, admin_id, "outsider.edit@cityos.test")
    tid = _task(client, admin_id)
    cid = client.post(f"/api/tasks/{tid}/comments",
                      json={"actor_id": admin_id, "content": "א", "mentions": [member_id]}).json()["id"]
    before = len(_unread_for(client, out))
    r = client.patch(f"/api/comments/{cid}",
                   json={"actor_id": admin_id, "content": "ב", "mentions": [member_id, out]})
    assert r.status_code == 200
    assert out not in (r.json().get("mentions") or [])
    assert len(_unread_for(client, out)) == before


def test_a_removed_member_can_no_longer_be_tagged(client, admin_id):
    """The rule follows membership, not the moment the tag was written."""
    uid = _outsider(client, admin_id, "outsider.removed@cityos.test")
    client.post("/api/boards/1/members",
                json={"actor_id": admin_id, "user_id": uid, "role": "editor"})
    tid = _task(client, admin_id)
    ok = client.post(f"/api/tasks/{tid}/comments",
                     json={"actor_id": admin_id, "content": "בזמן שהיה חבר", "mentions": [uid]})
    assert uid in (ok.json().get("mentions") or [])

    client.delete(f"/api/boards/1/members/{uid}?actor_id={admin_id}")
    after = client.post(f"/api/tasks/{tid}/comments",
                        json={"actor_id": admin_id, "content": "אחרי ההסרה", "mentions": [uid]})
    assert uid not in (after.json().get("mentions") or [])


def test_a_rule_cannot_name_someone_who_was_never_invited(client, admin_id):
    """Refused when written, not silently ignored when it runs."""
    out = _outsider(client, admin_id, "outsider.rule@cityos.test")
    bid = client.post("/api/boards", json={"name": "לוח לכלל", "user_id": admin_id}).json()["id"]
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "status_notify_person",
                          "config": {"t_status": "done", "a_person": out}})
    assert r.status_code == 400
    assert "הוזמנו ללוח" in r.json().get("detail", "")


def test_a_rule_stops_notifying_once_its_target_leaves_the_board(client, admin_id):
    """Membership is re-checked when the rule runs, not only when it was saved."""
    from models import Notification
    from sqlalchemy.orm import Session
    import main as cityos_main

    uid = _outsider(client, admin_id, "outsider.leaves@cityos.test")
    bid = client.post("/api/boards", json={"name": "לוח עוזב", "user_id": admin_id}).json()["id"]
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": uid, "role": "editor"})
    client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                json={"recipe_id": "status_notify_person",
                      "config": {"t_status": "done", "a_person": uid}})

    client.delete(f"/api/boards/{bid}/members/{uid}?actor_id={admin_id}")
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})

    with Session(cityos_main.engine) as db:
        got = db.query(Notification).filter(Notification.task_id == tid,
                                            Notification.user_id == uid).all()
    assert got == [], "a rule kept notifying someone taken off the board"
