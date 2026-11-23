"""A person is tagged on an item only if they can see that item.

The rule used to be "only board members may be tagged" (test_mention_membership.py,
test_people_membership.py), and for every role before assigned_only that was the
same thing as "only people who can see the item". An assigned_only member is on
the board and still cannot see most of its items — so tagging them on one of
those notified somebody about a row they then could not open, which is exactly
what the membership rule was written to stop.

So, for an assigned_only member who is not assigned to the item:

* an @mention in a comment (picked, typed, or added by editing) is dropped, the
  way a non-member's is — no stored mention, no notification;
* writing them into a people column that is NOT the permission column is
  dropped (PATCH custom_fields), or refused with 403 on the assignees route when
  the built-in assignees are not the permission column;
* writing them into the permission column IS allowed — that is how somebody is
  given an item at all — and it gives them the item.

An assigned_editor sees every item, so they stay taggable everywhere.
"""
import pytest

from conftest import join_primary_env


def AS(uid):
    return {"X-CityOS-User": str(uid)}


def _user(client, admin_id, name, email):
    for u in client.get("/api/users", headers=AS(admin_id)).json():
        if u.get("email") == email:
            uid = u["id"]
            break
    else:
        r = client.post("/api/users", headers=AS(admin_id),
                        json={"name": name, "email": email, "role": "member"})
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
    join_primary_env(client, uid)
    return uid


def _board_json(client, bid, uid):
    r = client.get(f"/api/boards/{bid}", headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, admin_id, bid, title):
    r = client.post("/api/tasks", headers=AS(admin_id), json={"board_id": bid, "title": title})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _cell(client, admin_id, bid, tid, col):
    t = next(t for t in _board_json(client, bid, admin_id)["tasks"] if t["id"] == tid)
    return t["custom_fields"].get(col) or []


def _mentions_of(client, uid):
    r = client.get("/api/notifications?limit=200", headers=AS(uid))
    assert r.status_code == 200, r.text
    return [n for n in r.json()["notifications"] if n.get("type") == "mention"]


def _assign(client, actor, tid, uid, action="add"):
    return client.post(f"/api/tasks/{tid}/assignees", headers=AS(actor),
                       json={"user_id": uid, "action": action})


@pytest.fixture
def ae(client, admin_id):
    return _user(client, admin_id, "בודק עורך משויכים", "test.assigned.editor@cityos.test")


@pytest.fixture
def ao(client, admin_id):
    return _user(client, admin_id, "בודק משויכים בלבד", "test.assigned.only@cityos.test")


@pytest.fixture
def board(client, admin_id, ae, ao, guinea_id):
    """A board with a people column "ppl" (not the permission column), an
    assigned_editor, an assigned_only member, a plain editor, one item the
    assigned_only member is on and one they are not."""
    r = client.post("/api/boards", headers=AS(admin_id), json={"name": "לוח תיוג משויכים"})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        join_primary_env(client, guinea_id)
        for uid, role in ((ae, "assigned_editor"), (ao, "assigned_only"), (guinea_id, "editor")):
            r = client.post(f"/api/boards/{bid}/members", headers=AS(admin_id),
                            json={"user_id": uid, "role": role})
            assert r.status_code == 200, r.text
        cols = _board_json(client, bid, admin_id)["columns"] + [
            {"id": "ppl", "type": "people", "title": "מבצע"}]
        r = client.patch(f"/api/boards/{bid}", headers=AS(admin_id), json={"columns": cols})
        assert r.status_code == 200, r.text
        theirs = _item(client, admin_id, bid, "של המשויך")
        hidden = _item(client, admin_id, bid, "לא שלו")
        assert _assign(client, admin_id, theirs, ao).status_code == 200
        yield {"id": bid, "theirs": theirs, "hidden": hidden}
    finally:
        client.delete(f"/api/boards/{bid}", headers=AS(admin_id))


# ── comments ─────────────────────────────────────────────────────────────

def test_a_comment_cannot_tag_someone_who_cannot_see_the_item(client, admin_id, ao, board):
    before = len(_mentions_of(client, ao))
    r = client.post(f"/api/tasks/{board['hidden']}/comments", headers=AS(admin_id),
                    json={"content": "תסתכל", "mentions": [ao]})
    assert r.status_code == 200, r.text
    assert ao not in (r.json().get("mentions") or []), "tagged on an item they cannot see"
    assert len(_mentions_of(client, ao)) == before, "notified about an item they cannot see"


def test_typing_their_name_does_not_tag_them_either(client, admin_id, ao, board):
    """The picker can be bypassed by typing — the server still has to hold."""
    name = next(u["name"] for u in client.get("/api/users", headers=AS(admin_id)).json()
                if u["id"] == ao)
    before = len(_mentions_of(client, ao))
    r = client.post(f"/api/tasks/{board['hidden']}/comments", headers=AS(admin_id),
                    json={"content": f"היי @{name} תסתכל"})
    assert r.status_code == 200, r.text
    assert ao not in (r.json().get("mentions") or [])
    assert len(_mentions_of(client, ao)) == before


def test_editing_a_comment_cannot_add_them(client, admin_id, ao, guinea_id, board):
    cid = client.post(f"/api/tasks/{board['hidden']}/comments", headers=AS(admin_id),
                      json={"content": "א", "mentions": [guinea_id]}).json()["id"]
    before = len(_mentions_of(client, ao))
    r = client.patch(f"/api/comments/{cid}", headers=AS(admin_id),
                     json={"content": "ב", "mentions": [guinea_id, ao]})
    assert r.status_code == 200, r.text
    assert ao not in (r.json().get("mentions") or [])
    assert len(_mentions_of(client, ao)) == before


def test_a_comment_tags_them_on_an_item_they_are_assigned_to(client, admin_id, ao, board):
    before = len(_mentions_of(client, ao))
    r = client.post(f"/api/tasks/{board['theirs']}/comments", headers=AS(admin_id),
                    json={"content": "בשבילך", "mentions": [ao]})
    assert r.status_code == 200, r.text
    assert ao in (r.json().get("mentions") or [])
    assert len(_mentions_of(client, ao)) == before + 1


def test_an_assigned_editor_is_taggable_on_any_item_because_they_see_them_all(
        client, admin_id, ae, board):
    r = client.post(f"/api/tasks/{board['hidden']}/comments", headers=AS(admin_id),
                    json={"content": "לידיעתך", "mentions": [ae]})
    assert r.status_code == 200, r.text
    assert ae in (r.json().get("mentions") or [])


# ── people columns ───────────────────────────────────────────────────────

def test_a_people_column_that_is_not_the_permission_column_drops_them(
        client, admin_id, ao, guinea_id, board):
    bid, tid = board["id"], board["hidden"]
    r = client.patch(f"/api/tasks/{tid}", headers=AS(admin_id),
                     json={"custom_fields": {"ppl": [guinea_id, ao]}})
    assert r.status_code == 200, r.text
    stored = _cell(client, admin_id, bid, tid, "ppl")
    assert guinea_id in stored, "the editor was dropped too — the rule is too wide"
    assert ao not in stored, "named in a column on an item they cannot see"
    # …and naming them there did not quietly hand them the item
    assert tid not in {t["id"] for t in _board_json(client, bid, ao)["tasks"]}


def test_the_same_column_keeps_them_on_an_item_they_can_see(client, admin_id, ao, board):
    bid, tid = board["id"], board["theirs"]
    r = client.patch(f"/api/tasks/{tid}", headers=AS(admin_id),
                     json={"custom_fields": {"ppl": [ao]}})
    assert r.status_code == 200, r.text
    assert ao in _cell(client, admin_id, bid, tid, "ppl")


def test_the_assignees_route_refuses_them_when_assignees_is_not_the_permission_column(
        client, admin_id, ao, board):
    bid = board["id"]
    r = client.patch(f"/api/boards/{bid}", headers=AS(admin_id), json={"perm_column": "ppl"})
    assert r.status_code == 200, r.text
    # under ppl they can see nothing yet, so the built-in column is not theirs to be in
    r = _assign(client, admin_id, board["hidden"], ao)
    assert r.status_code == 403, r.text
    # once ppl gives them the item, the built-in column may name them on it
    r = client.patch(f"/api/tasks/{board['hidden']}", headers=AS(admin_id),
                     json={"custom_fields": {"ppl": [ao]}})
    assert r.status_code == 200, r.text
    assert ao in _cell(client, admin_id, bid, board["hidden"], "ppl")
    r = _assign(client, admin_id, board["hidden"], ao)
    assert r.status_code == 200, r.text


def test_putting_them_in_the_permission_column_is_allowed_and_gives_them_the_item(
        client, admin_id, ao, board):
    bid, tid = board["id"], board["hidden"]
    assert tid not in {t["id"] for t in _board_json(client, bid, ao)["tasks"]}
    r = _assign(client, admin_id, tid, ao)
    assert r.status_code == 200, r.text
    rows = {t["id"]: t.get("my_perm") for t in _board_json(client, bid, ao)["tasks"]}
    assert rows.get(tid) == "edit", rows
    # and now that they can see it, they can be tagged on it
    r = client.post(f"/api/tasks/{tid}/comments", headers=AS(admin_id),
                    json={"content": "עכשיו זה שלך", "mentions": [ao]})
    assert ao in (r.json().get("mentions") or [])
