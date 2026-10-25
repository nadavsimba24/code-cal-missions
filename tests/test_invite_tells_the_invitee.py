"""Being added somewhere has to say so — to the person it happened to.

A board invitation has always emailed the invitee and left them an in-app
notification. Adding somebody to a *workspace* (סביבה) wrote the row and said
nothing at all: no mail, no notification, nothing in the app to see. Somebody
added to a workspace and waiting to hear about it was waiting for nothing.

These pin both paths, and pin the rule they share: only a genuine new
membership speaks. A role change must not read as a fresh invitation.
"""
import main as cityos_main


def _captured(monkeypatch):
    """Replace the sender; collect (to, subject, html) instead of sending."""
    out = []
    monkeypatch.setattr(cityos_main, "_send_email",
                        lambda to, subject, html: out.append((to, subject, html)) or True)
    return out


def _notifs(client, uid):
    return client.get(f"/api/notifications?user_id={uid}&limit=100"
                      ).json()["notifications"]


def test_a_new_workspace_member_is_told(client, admin_id, guinea_id, monkeypatch):
    sent = _captured(monkeypatch)
    env = client.post("/api/environments",
                      json={"actor_id": admin_id, "name": "סביבת דואר"}).json()
    eid = env["id"]

    r = client.post(f"/api/environments/{eid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "member"})
    assert r.status_code == 200, r.text
    assert r.json()["invited"] is True

    assert len(sent) == 1, "a new workspace member got no mail"
    to, subject, html = sent[0]
    assert subject == 'צורפת לסביבת העבודה "סביבת דואר" במערכת missions'
    # the mail must not promise boards the workspace does not grant
    assert "סביבת דואר" in html and "לוח ציבורי" in html
    assert "צירפ/ה אותך לסביבת העבודה" in html and "ממערכת missions" in html
    assert any("סביבת דואר" in n["title"] for n in _notifs(client, guinea_id))


def test_a_role_change_is_not_a_new_invitation(client, admin_id, guinea_id, monkeypatch):
    """Promoting somebody already inside must not mail them again."""
    env = client.post("/api/environments",
                      json={"actor_id": admin_id, "name": "סביבת תפקידים"}).json()
    eid = env["id"]
    client.post(f"/api/environments/{eid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "member"})

    sent = _captured(monkeypatch)        # armed only for the second call
    r = client.post(f"/api/environments/{eid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "manager"})
    assert r.status_code == 200, r.text
    assert r.json()["invited"] is False
    assert sent == [], "a role change was mailed as if it were an invitation"


def test_a_new_board_member_is_still_told(client, admin_id, guinea_id, monkeypatch):
    """The path that already worked, kept working — it is the one the workspace
    invitation was modelled on."""
    sent = _captured(monkeypatch)
    boards = client.get(f"/api/boards?user_id={admin_id}").json()
    bid = (boards["boards"] if isinstance(boards, dict) else boards)[0]["id"]
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    sent.clear()

    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert r.status_code == 200, r.text
    assert len(sent) == 1, "a new board member got no mail"
    to, subject, html = sent[0]
    assert subject.startswith("צורפת ללוח ") and "במערכת missions" in subject
    # "כניסה ללוח" has to land on the board, not on the home screen
    assert f"/#/board/{bid}" in html and "כניסה ללוח" in html
