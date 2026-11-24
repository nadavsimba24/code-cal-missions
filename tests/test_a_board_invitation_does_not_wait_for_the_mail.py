"""Inviting somebody to a board answers before the invitation mail is sent.

_send_email is a blocking HTTPS call to the provider with a ten-second
timeout, and POST /api/boards/{id}/members used to make it inside the
request. The admin who pressed "הזמן" waited on SendGrid before the members
dialog could redraw its list — for a message nothing on screen depends on.
Comments made the same move earlier (_queue_item_mails); invitations had been
left behind.

TestClient drains background tasks before it returns, so through the client
the mail still looks synchronous — which keeps the invitation tests that
assert on it straight after the POST meaningful. The ORDER is therefore
pinned by calling the route function directly with a BackgroundTasks of our
own: nothing is sent while the route runs, and exactly the one invitation is
sent when the queue is run.
"""
import asyncio

from fastapi import BackgroundTasks

import main as cityos_main


def test_the_invitation_mail_is_sent_after_the_response(client, admin_id,
                                                         guinea_id, monkeypatch):
    sent = []
    monkeypatch.setattr(cityos_main, "_send_email",
                        lambda to, subject, html: sent.append((to, subject)) or True)
    board = client.post("/api/boards", json={"actor_id": admin_id,
                                             "name": "לוח הזמנה בלי המתנה"}).json()
    bid = board["id"]
    try:
        bg = BackgroundTasks()
        out = cityos_main.add_board_member(
            bid, {"user_id": guinea_id, "role": "editor"},
            request=None, background=bg, actor_id=admin_id)
        assert out["invited"] is True
        assert sent == [], "the route sent the mail before it answered"

        asyncio.run(bg())
        assert len(sent) == 1, "the queued invitation was never sent"
        assert sent[0][1] == 'צורפת ללוח "לוח הזמנה בלי המתנה" במערכת missions'
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={admin_id}")


def test_a_role_change_queues_no_mail(client, admin_id, guinea_id, monkeypatch):
    """Deferring the send must not widen WHO is sent one: a member whose role
    changes was never mailed, and is not queued one now."""
    board = client.post("/api/boards", json={"actor_id": admin_id,
                                             "name": "לוח שינוי תפקיד"}).json()
    bid = board["id"]
    try:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
        sent = []
        monkeypatch.setattr(cityos_main, "_send_email",
                            lambda to, subject, html: sent.append(to) or True)
        bg = BackgroundTasks()
        out = cityos_main.add_board_member(
            bid, {"user_id": guinea_id, "role": "viewer"},
            request=None, background=bg, actor_id=admin_id)
        assert out["invited"] is False
        asyncio.run(bg())
        assert sent == [], "a role change was mailed as if it were an invitation"
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={admin_id}")
