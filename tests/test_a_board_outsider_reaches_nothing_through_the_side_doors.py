"""A user who may not open a board reaches none of it by another route.

The penetration test of 2026-11 (BOLA) found three routes that answered a
member for boards they were never invited to, while the direct route to the
same object answered 403:

  - GET   /api/tasks?board_id=…  listed the board's items in full
          (GET /api/tasks/{id} refused them);
  - PATCH /api/boards/{id}        renamed the board
          (GET /api/boards/{id} refused it);
  - GET   /api/files/{token}      served any attachment to whoever had its token
          (GET /api/tasks/{id}/files refused it).

The rule pinned here is that both doors give the same answer: what the direct
read would refuse, the list, the update and the file refuse as well — and
being invited is still enough to get through all three.
"""

H = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    b = client.post("/api/boards", json={"name": name}, headers=H(admin_id)).json()
    bid = b["id"]
    gid = client.get(f"/api/boards/{bid}", headers=H(admin_id)).json()["groups"][0]["id"]
    return bid, gid


def _invite(client, admin_id, bid, uid, role):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"user_id": uid, "role": role}, headers=H(admin_id))
    assert r.status_code == 200, r.text


def test_the_task_list_refuses_a_board_the_direct_read_refuses(client, admin_id, guinea_id):
    bid, gid = _board(client, admin_id, "לוח BOLA משימות")
    try:
        t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                            "title": "פנייה סודית", "description": "פרטים מזהים"},
                        headers=H(admin_id)).json()
        # the control: the direct read is refused
        assert client.get(f"/api/tasks/{t['id']}", headers=H(guinea_id)).status_code == 403
        # and the list now says the same thing, instead of the board's items
        r = client.get(f"/api/tasks?board_id={bid}", headers=H(guinea_id))
        assert r.status_code == 403, r.text
        # without a board, the item is simply not among the ones listed
        ids = {x["id"] for x in client.get("/api/tasks", headers=H(guinea_id)).json()}
        assert t["id"] not in ids
        # invited, the same person sees it on both doors
        _invite(client, admin_id, bid, guinea_id, "viewer")
        r = client.get(f"/api/tasks?board_id={bid}", headers=H(guinea_id))
        assert r.status_code == 200 and t["id"] in {x["id"] for x in r.json()}
    finally:
        client.delete(f"/api/boards/{bid}", headers=H(admin_id))


def test_a_board_is_changed_only_by_someone_who_may_change_it(client, admin_id, guinea_id):
    bid, _gid = _board(client, admin_id, "לוח BOLA עדכון")
    try:
        # not invited: refused, and the name did not move
        r = client.patch(f"/api/boards/{bid}", json={"name": "BOLA_PoC"}, headers=H(guinea_id))
        assert r.status_code == 403, r.text
        # a viewer reads the board but does not change it either
        _invite(client, admin_id, bid, guinea_id, "viewer")
        r = client.patch(f"/api/boards/{bid}", json={"name": "BOLA_PoC"}, headers=H(guinea_id))
        assert r.status_code == 403, r.text
        assert client.get(f"/api/boards/{bid}", headers=H(admin_id)).json()["name"] == "לוח BOLA עדכון"
        # an editor still renames it, as before
        _invite(client, admin_id, bid, guinea_id, "editor")
        r = client.patch(f"/api/boards/{bid}", json={"name": "שם של עורך"}, headers=H(guinea_id))
        assert r.status_code == 200 and r.json()["name"] == "שם של עורך"
    finally:
        client.delete(f"/api/boards/{bid}", headers=H(admin_id))


def test_an_attachment_is_served_only_to_who_may_see_its_item(client, admin_id, guinea_id):
    bid, gid = _board(client, admin_id, "לוח BOLA קבצים")
    try:
        t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid, "title": "עם קובץ"},
                        headers=H(admin_id)).json()
        up = client.post("/api/upload", files={"file": ("secret.txt", b"board-only", "text/plain")},
                         headers=H(admin_id)).json()
        tok = up["url"].rsplit("/", 1)[-1]
        r = client.post(f"/api/tasks/{t['id']}/comments",
                        json={"content": "מצורף", "attachments": [up]}, headers=H(admin_id))
        assert r.status_code == 200, r.text

        # the control, and the file itself: both refused to an outsider
        assert client.get(f"/api/tasks/{t['id']}/files", headers=H(guinea_id)).status_code == 403
        assert client.get(f"/api/files/{tok}", headers=H(guinea_id)).status_code == 403
        # the board's own people get it
        assert client.get(f"/api/files/{tok}", headers=H(admin_id)).content == b"board-only"
        _invite(client, admin_id, bid, guinea_id, "viewer")
        r = client.get(f"/api/files/{tok}", headers=H(guinea_id))
        assert r.status_code == 200 and r.content == b"board-only"
    finally:
        client.delete(f"/api/boards/{bid}", headers=H(admin_id))


def test_an_upload_not_yet_attached_is_its_uploaders_alone(client, guinea_id, member_id):
    """Between the upload and the save that attaches it, the file belongs to
    nothing — the person composing still sees their own preview, nobody else
    does."""
    up = client.post("/api/upload", files={"file": ("draft.txt", b"mine", "text/plain")},
                     headers=H(guinea_id)).json()
    tok = up["url"].rsplit("/", 1)[-1]
    assert client.get(f"/api/files/{tok}", headers=H(guinea_id)).content == b"mine"
    assert client.get(f"/api/files/{tok}", headers=H(member_id)).status_code == 403


# ── attaching is checked too ────────────────────────────────────────────────
# Found in code review after the fix above: reading was checked against what a
# file is attached to, but attaching was not checked at all — so anybody who
# learned a token attached it to something of their own and read it from
# there, or set it as their avatar and published it to everybody.

def _secret(client, admin_id):
    """A file on a board nobody else is on."""
    bid, gid = _board(client, admin_id, "לוח הסוד")
    t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid, "title": "סוד"},
                    headers=H(admin_id)).json()
    up = client.post("/api/upload", files={"file": ("s.txt", b"SECRET", "text/plain")},
                     headers=H(admin_id)).json()
    client.post(f"/api/tasks/{t['id']}/comments", json={"content": "x", "attachments": [up]},
                headers=H(admin_id))
    return bid, up


def test_a_token_cannot_be_attached_by_someone_who_cannot_read_it(client, admin_id, guinea_id):
    secret_board, up = _secret(client, admin_id)
    tok = up["url"].rsplit("/", 1)[-1]
    mine, gid = _board(client, admin_id, "לוח של guinea")
    _invite(client, admin_id, mine, guinea_id, "editor")
    try:
        t = client.post("/api/tasks", json={"board_id": mine, "group_id": gid, "title": "שלי"},
                        headers=H(guinea_id)).json()
        # in a comment, in a comment edit, in a cell, in a new item, as an avatar
        r = client.post(f"/api/tasks/{t['id']}/comments",
                        json={"content": "x", "attachments": [up]}, headers=H(guinea_id))
        assert r.status_code == 403, r.text
        c = client.post(f"/api/tasks/{t['id']}/comments", json={"content": "נקי"},
                        headers=H(guinea_id)).json()
        r = client.patch(f"/api/comments/{c['id']}", json={"content": "x", "attachments": [up]},
                         headers=H(guinea_id))
        assert r.status_code == 403, r.text
        r = client.patch(f"/api/tasks/{t['id']}", json={"custom_fields": {"files": [up]}},
                         headers=H(guinea_id))
        assert r.status_code == 403, r.text
        r = client.post("/api/tasks", json={"board_id": mine, "group_id": gid, "title": "חדש",
                                            "custom_fields": {"files": [up]}}, headers=H(guinea_id))
        assert r.status_code == 403, r.text
        r = client.patch(f"/api/users/{guinea_id}", json={"avatar_url": up["url"]},
                         headers=H(guinea_id))
        assert r.status_code == 403, r.text
        # and after all of it, still not theirs
        assert client.get(f"/api/files/{tok}", headers=H(guinea_id)).status_code == 403
    finally:
        for b in (secret_board, mine):
            client.delete(f"/api/boards/{b}", headers=H(admin_id))


def test_a_link_in_a_cell_that_is_not_a_files_column_opens_nothing(client, admin_id, guinea_id):
    """Only a files column attaches. A link typed into anything else is text."""
    bid, gid = _board(client, admin_id, "לוח טקסט")
    _invite(client, admin_id, bid, guinea_id, "viewer")
    up = client.post("/api/upload", files={"file": ("t.txt", b"T", "text/plain")},
                     headers=H(admin_id)).json()
    try:
        client.post("/api/tasks", json={"board_id": bid, "group_id": gid, "title": "פריט עם קישור בטקסט",
                                        "custom_fields": {"notes": "ראו " + up["url"]}},
                    headers=H(admin_id))
        tok = up["url"].rsplit("/", 1)[-1]
        assert client.get(f"/api/files/{tok}", headers=H(guinea_id)).status_code == 403
    finally:
        client.delete(f"/api/boards/{bid}", headers=H(admin_id))


def test_your_own_upload_attaches_and_your_colleagues_read_it(client, admin_id, guinea_id, member_id):
    bid, gid = _board(client, admin_id, "לוח משותף")
    _invite(client, admin_id, bid, guinea_id, "editor")
    _invite(client, admin_id, bid, member_id, "viewer")
    try:
        t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid, "title": "פריט עם קובץ שלי"},
                        headers=H(guinea_id)).json()
        up = client.post("/api/upload", files={"file": ("m.txt", b"MINE", "text/plain")},
                         headers=H(guinea_id)).json()
        r = client.post(f"/api/tasks/{t['id']}/comments", json={"content": "x", "attachments": [up]},
                        headers=H(guinea_id))
        assert r.status_code == 200, r.text
        tok = up["url"].rsplit("/", 1)[-1]
        assert client.get(f"/api/files/{tok}", headers=H(member_id)).content == b"MINE"
    finally:
        client.delete(f"/api/boards/{bid}", headers=H(admin_id))
