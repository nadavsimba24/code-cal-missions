"""People columns may only name users who were invited to the board.

Tagging an outsider used to be possible from every people column — the built-in
"אחראים" column, a board-defined people column, and the new-item form. That
notified someone who then could not open the board, and put a name on an item
its owner had no way to reach. The rule is enforced on the server; the pickers
only stop offering them.

Removal is deliberately left open, so a tag made before this rule can be cleaned
up instead of being frozen onto the item forever.
"""


def _board(client, admin_id, name="לוח שיוך"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _task(client, bid, admin_id, **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                           "user_id": admin_id, **kw}).json()


def _get(client, bid, uid):
    return client.get(f"/api/boards/{bid}?user_id={uid}").json()


def _outsider(client, admin_id, email="test.outsider@cityos.test"):
    """A real user who is a member of no board (and not a workspace admin —
    a workspace admin reaches every board and stays taggable by design)."""
    for u in client.get(f"/api/users?user_id={admin_id}").json():
        if u.get("email") == email:
            return u["id"]
    return client.post("/api/users", json={"actor_id": admin_id, "name": "בודק חיצוני",
                                           "email": email, "role": "member"}).json()["id"]


def _assign(client, tid, uid, actor, action="add"):
    return client.post(f"/api/tasks/{tid}/assignees",
                       json={"user_id": uid, "action": action, "actor_id": actor})


# ── built-in "אחראים" column ────────────────────────────────────────────────

def test_cannot_assign_a_non_member(client, admin_id):
    bid = _board(client, admin_id)
    tid = _task(client, bid, admin_id)["id"]
    r = _assign(client, tid, _outsider(client, admin_id), admin_id)
    assert r.status_code == 403, r.text
    assert not _get(client, bid, admin_id)["tasks"][0]["assignees"]


def test_can_assign_a_member(client, admin_id, member_id):
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    tid = _task(client, bid, admin_id)["id"]
    r = _assign(client, tid, member_id, admin_id)
    assert r.status_code == 200, r.text
    assert member_id in [a["id"] for a in r.json()["assignees"]]


def test_removing_survives_losing_membership(client, admin_id, guinea_id):
    """Assign while a member, then un-invite: the tag must still be removable."""
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    tid = _task(client, bid, admin_id)["id"]
    assert _assign(client, tid, guinea_id, admin_id).status_code == 200
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    r = _assign(client, tid, guinea_id, admin_id, action="remove")
    assert r.status_code == 200, r.text
    assert guinea_id not in [a["id"] for a in r.json()["assignees"]]


# ── board-defined people column ─────────────────────────────────────────────

def _people_col(client, bid, admin_id):
    cols = _get(client, bid, admin_id)["columns"] + [{"id": "ppl", "type": "people", "title": "אנשים"}]
    client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": cols})


def test_people_column_drops_a_non_member(client, admin_id, member_id):
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    _people_col(client, bid, admin_id)
    tid = _task(client, bid, admin_id)["id"]
    out = _outsider(client, admin_id)
    r = client.patch(f"/api/tasks/{tid}",
                     json={"user_id": admin_id, "custom_fields": {"ppl": [member_id, out]}})
    assert r.status_code == 200, r.text
    stored = _get(client, bid, admin_id)["tasks"][0]["custom_fields"].get("ppl") or []
    assert member_id in stored and out not in stored


def test_people_column_keeps_an_id_already_stored(client, admin_id, guinea_id):
    """A value written before the rule stays put, so the cell is still saveable."""
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    _people_col(client, bid, admin_id)
    tid = _task(client, bid, admin_id)["id"]
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "custom_fields": {"ppl": [guinea_id]}})
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    r = client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "custom_fields": {"ppl": [guinea_id]}})
    assert r.status_code == 200, r.text
    assert _get(client, bid, admin_id)["tasks"][0]["custom_fields"].get("ppl") == [guinea_id]


# ── creation path ───────────────────────────────────────────────────────────

def test_create_task_ignores_a_non_member_assignee(client, admin_id):
    bid = _board(client, admin_id)
    t = _task(client, bid, admin_id, assignee_ids=[_outsider(client, admin_id)])
    assert [a["id"] for a in (t.get("assignees") or [])] == []


# ── what the pickers build from ─────────────────────────────────────────────

def test_board_payload_exposes_its_members(client, admin_id, member_id):
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    ids = {m["id"] for m in _get(client, bid, admin_id)["members"]}
    assert {admin_id, member_id} <= ids
    assert _outsider(client, admin_id) not in ids
