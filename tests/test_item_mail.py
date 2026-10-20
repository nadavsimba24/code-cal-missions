"""Being put on a record, and being tagged in its conversation — by mail.

Both events already wrote an in-app notification, and an in-app notification
only reaches somebody who is already in the app. These two are the events whose
whole point is the opposite: they are addressed to a person who is not looking
at the board, and who has no way to learn that their name is now on something.

The mail is built before the commit and sent after it, so nothing is mailed
about a change that rolled back — and every reason NOT to send lives in one
place (_item_mail) rather than at the five call sites that can cause one.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import User


def _captured(monkeypatch):
    out = []
    monkeypatch.setattr(cityos_main, "_send_email",
                        lambda to, subject, html: out.append((to, subject, html)) or True)
    return out


def _board(client, admin_id, invite=(), name="לוח דואר"):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    for uid in invite:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": "editor"})
    return bid


def _item(client, bid, admin_id, title="רשומה", **extra):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **extra}).json()["id"]


def _name(uid):
    with Session(cityos_main.engine) as db:
        return db.query(User.name).filter(User.id == uid).scalar()


def _email(uid):
    with Session(cityos_main.engine) as db:
        return db.query(User.email).filter(User.id == uid).scalar()


# ── 1. שוייכת לרשומה ───────────────────────────────────────────────────────
def test_being_assigned_to_a_record_is_mailed(client, admin_id, guinea_id, monkeypatch):
    bid = _board(client, admin_id, invite=[guinea_id], name="תשתיות")
    tid = _item(client, bid, admin_id, "מדרכה שבורה")
    sent = _captured(monkeypatch)

    r = client.post(f"/api/tasks/{tid}/assignees",
                    json={"actor_id": admin_id, "user_id": guinea_id})
    assert r.status_code == 200, r.text

    assert len(sent) == 1, sent
    to, subject, html = sent[0]
    assert to == _email(guinea_id)
    # The wording, word for word as the product wrote it: the board's name in
    # quotes, MISSIONS in capitals in the subject and lower case in the
    # sentence. Spelled out here rather than built from a helper, so a change
    # to any of it is a change somebody has to make on purpose.
    assert subject == 'שוייכת לרשומה בלוח "תשתיות" במערכת MISSIONS'
    assert f"שלום {_name(guinea_id)}," in html
    assert (f'שויכת ע"י <b>{_name(admin_id)}</b> לרשומה '
            f'<b>"מדרכה שבורה"</b> בלוח <b>תשתיות</b> במערכת missions.') in html
    assert "כניסה לרשומה" in html
    assert "מייל זה נשלח באופן אוטומטי ממערכת missions ואין להגיב לו." in html


def test_the_button_lands_on_the_record_itself(client, admin_id, guinea_id, monkeypatch):
    """"כניסה לרשומה" promises the record, so it links to the record's own deep
    link — the route the app already reads — and not to the home screen."""
    bid = _board(client, admin_id, invite=[guinea_id])
    tid = _item(client, bid, admin_id)
    sent = _captured(monkeypatch)
    client.post(f"/api/tasks/{tid}/assignees",
                json={"actor_id": admin_id, "user_id": guinea_id})
    assert f"#/board/{bid}/item/{tid}" in sent[0][2]


def test_an_item_created_with_somebody_on_it_mails_them(client, admin_id, guinea_id, monkeypatch):
    """Assignment at creation is assignment: the half that went unmailed would
    be the commonest one of all."""
    bid = _board(client, admin_id, invite=[guinea_id])
    sent = _captured(monkeypatch)
    _item(client, bid, admin_id, "גדר חדשה", assignee_ids=[guinea_id])
    assert len(sent) == 1, sent
    assert "גדר חדשה" in sent[0][2] and 'שויכת ע"י' in sent[0][2]


def test_being_named_in_a_people_column_is_being_assigned(client, admin_id, guinea_id, monkeypatch):
    bid = _board(client, admin_id, invite=[guinea_id])
    r = client.patch(f"/api/boards/{bid}",
                     json={"user_id": admin_id,
                           "columns": [{"type": "people", "title": "מבצע"}]})
    assert r.status_code == 200, r.text
    cid = next(c["id"] for c in r.json()["columns"] if c["type"] == "people")
    tid = _item(client, bid, admin_id, "ניקוי כביש")
    sent = _captured(monkeypatch)

    r = client.patch(f"/api/tasks/{tid}",
                     json={"actor_id": admin_id, "custom_fields": {cid: [guinea_id]}})
    assert r.status_code == 200, r.text
    assert len(sent) == 1, sent
    assert "ניקוי כביש" in sent[0][2]


def test_assigning_somebody_already_on_the_record_mails_nothing(client, admin_id, guinea_id,
                                                                monkeypatch):
    bid = _board(client, admin_id, invite=[guinea_id])
    tid = _item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/assignees", json={"actor_id": admin_id, "user_id": guinea_id})
    sent = _captured(monkeypatch)
    client.post(f"/api/tasks/{tid}/assignees", json={"actor_id": admin_id, "user_id": guinea_id})
    assert sent == []


def test_putting_yourself_on_a_record_does_not_mail_you(client, admin_id, monkeypatch):
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    sent = _captured(monkeypatch)
    client.post(f"/api/tasks/{tid}/assignees", json={"actor_id": admin_id, "user_id": admin_id})
    assert sent == [], "somebody was mailed about their own keystroke"


# ── 2. תוייגת בשיחה ────────────────────────────────────────────────────────
def test_being_tagged_in_a_conversation_is_mailed(client, admin_id, guinea_id, monkeypatch):
    bid = _board(client, admin_id, invite=[guinea_id], name="פניות")
    tid = _item(client, bid, admin_id, "עץ שנפל")
    sent = _captured(monkeypatch)

    r = client.post(f"/api/tasks/{tid}/comments",
                    json={"actor_id": admin_id, "content": "תוכל לטפל?",
                          "mentions": [guinea_id]})
    assert r.status_code == 200, r.text

    assert len(sent) == 1, sent
    to, subject, html = sent[0]
    assert to == _email(guinea_id)
    # בשיחה, not ברשומה: what happened is that somebody was named in the
    # conversation. Same quoting and capitalisation as the mail above.
    assert subject == 'תוייגת בשיחה בלוח "פניות" במערכת MISSIONS'
    assert f"שלום {_name(guinea_id)}," in html
    assert (f'תוייגת ע"י <b>{_name(admin_id)}</b> בשיחה ברשומה '
            f'<b>"עץ שנפל"</b> בלוח <b>פניות</b> במערכת missions.') in html
    assert "כניסה לשיחה" in html
    assert f"#/board/{bid}/item/{tid}" in html
    assert "מייל זה נשלח באופן אוטומטי ממערכת missions ואין להגיב לו." in html


def test_a_tag_typed_as_at_name_mails_too(client, admin_id, guinea_id, monkeypatch):
    """Typing "@שם" bypasses the picker, and it is still a tag."""
    bid = _board(client, admin_id, invite=[guinea_id])
    tid = _item(client, bid, admin_id)
    sent = _captured(monkeypatch)
    client.post(f"/api/tasks/{tid}/comments",
                json={"actor_id": admin_id, "content": f"@{_name(guinea_id)} נא לבדוק"})
    assert len(sent) == 1, sent
    assert "כניסה לשיחה" in sent[0][2]


def test_a_tag_added_by_editing_a_comment_mails_the_newcomer_only(client, admin_id, guinea_id,
                                                                  member_id, monkeypatch):
    bid = _board(client, admin_id, invite=[guinea_id, member_id])
    tid = _item(client, bid, admin_id)
    cid = client.post(f"/api/tasks/{tid}/comments",
                      json={"actor_id": admin_id, "content": "ראשון",
                            "mentions": [guinea_id]}).json()["id"]
    sent = _captured(monkeypatch)

    r = client.patch(f"/api/comments/{cid}",
                     json={"actor_id": admin_id, "content": "ראשון ועוד",
                           "mentions": [guinea_id, member_id]})
    assert r.status_code == 200, r.text
    assert len(sent) == 1, "the person already tagged was mailed again"
    assert sent[0][0] == _email(member_id)


def test_tagging_yourself_mails_nothing(client, admin_id, monkeypatch):
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    sent = _captured(monkeypatch)
    client.post(f"/api/tasks/{tid}/comments",
                json={"actor_id": admin_id, "content": "לעצמי", "mentions": [admin_id]})
    assert sent == []


def test_a_comment_with_no_tags_mails_nobody(client, admin_id, guinea_id, monkeypatch):
    """A conversation is not a mailing list. Only a tag speaks."""
    bid = _board(client, admin_id, invite=[guinea_id])
    tid = _item(client, bid, admin_id)
    sent = _captured(monkeypatch)
    client.post(f"/api/tasks/{tid}/comments", json={"actor_id": admin_id, "content": "סתם הערה"})
    assert sent == []


# ── what stops a send ──────────────────────────────────────────────────────
def test_a_board_with_notifications_off_mails_nothing(client, admin_id, guinea_id, monkeypatch):
    """The switch a board admin has already got means no notifications. Mail is
    a notification, and the loudest one."""
    bid = _board(client, admin_id, invite=[guinea_id])
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id,
                                                 "notifications_enabled": False})
    assert r.status_code == 200, r.text
    tid = _item(client, bid, admin_id)
    sent = _captured(monkeypatch)
    client.post(f"/api/tasks/{tid}/assignees", json={"actor_id": admin_id, "user_id": guinea_id})
    client.post(f"/api/tasks/{tid}/comments",
                json={"actor_id": admin_id, "content": "היי", "mentions": [guinea_id]})
    assert sent == []


def test_a_recipient_with_no_address_is_skipped_not_crashed(client, admin_id, guinea_id,
                                                            monkeypatch):
    with Session(cityos_main.engine) as db:
        u = db.query(User).filter(User.id == guinea_id).first()
        kept, u.email = u.email, ""
        db.commit()
    try:
        bid = _board(client, admin_id, invite=[guinea_id])
        tid = _item(client, bid, admin_id)
        sent = _captured(monkeypatch)
        r = client.post(f"/api/tasks/{tid}/assignees",
                        json={"actor_id": admin_id, "user_id": guinea_id})
        assert r.status_code == 200, "the assignment itself must still go through"
        assert sent == []
    finally:
        with Session(cityos_main.engine) as db:
            db.query(User).filter(User.id == guinea_id).first().email = kept
            db.commit()


def test_a_title_with_angle_brackets_cannot_close_a_tag(client, admin_id, guinea_id, monkeypatch):
    """An item called "<b>דחוף</b> & חניה" is an ordinary title. Interpolated
    raw it would be markup in somebody's inbox."""
    bid = _board(client, admin_id, invite=[guinea_id])
    tid = _item(client, bid, admin_id, "<b>דחוף</b> & חניה")
    sent = _captured(monkeypatch)
    client.post(f"/api/tasks/{tid}/assignees", json={"actor_id": admin_id, "user_id": guinea_id})
    html = sent[0][2]
    assert "&lt;b&gt;דחוף&lt;/b&gt; &amp; חניה" in html
    assert "<b>דחוף</b>" not in html


def test_the_mail_goes_out_after_the_write_lands(client, admin_id, guinea_id, monkeypatch):
    """Built before the commit, sent after it. A mail sent from inside the
    transaction can describe an assignment that then rolls back."""
    seen = {}

    def _spy(to, subject, html):
        with Session(cityos_main.engine) as db:
            t = db.query(cityos_main.Task).filter(cityos_main.Task.id == seen["tid"]).first()
            seen["assigned"] = guinea_id in [u.id for u in t.assignees]
        return True

    bid = _board(client, admin_id, invite=[guinea_id])
    seen["tid"] = _item(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "_send_email", _spy)
    client.post(f"/api/tasks/{seen['tid']}/assignees",
                json={"actor_id": admin_id, "user_id": guinea_id})
    assert seen.get("assigned") is True, "the mail went out before the row was committed"
