"""A deactivated account is not somebody you can invite, tag or name.

Deactivating a user used to be a flag on a row and nothing more: they stayed in
the invite dropdown of every board and every environment, stayed in the people
columns and the @-menu, and could be assigned an item — so "לא פעיל" described
the account without changing anything anyone could do with it.

The rule here is that deactivation ends participation. One gate says so
(`main._can_be_assigned`), which is what every tagging path already asks, and
the invitation endpoints refuse on their own because an invitation is a grant of
access and must not depend on the picker having filtered.

Removal and clearing stay open throughout, for the same reason they do when
somebody loses board membership: a tag or an override made while the account was
live has to be cleanable by hand, not frozen onto the item forever.
"""
import contextlib


def _board(client, admin_id, name="לוח מושבתים"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _task(client, bid, admin_id, **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                           "user_id": admin_id, **kw}).json()


def _get(client, bid, uid):
    return client.get(f"/api/boards/{bid}?user_id={uid}").json()


def _invite(client, bid, admin_id, uid, role="editor"):
    return client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": uid, "role": role})


def _assign(client, tid, uid, actor, action="add"):
    return client.post(f"/api/tasks/{tid}/assignees",
                       json={"user_id": uid, "action": action, "actor_id": actor})


@contextlib.contextmanager
def _deactivated(client, admin_id, uid):
    """Turn an account off for the body of the test, and back on afterwards."""
    r = client.patch(f"/api/users/{uid}", json={"actor_id": admin_id, "is_active": False})
    assert r.status_code == 200, r.text
    try:
        yield uid
    finally:
        client.patch(f"/api/users/{uid}", json={"actor_id": admin_id, "is_active": True})


# ── invitations ─────────────────────────────────────────────────────────────

def test_board_invite_list_drops_a_deactivated_user(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    before = {u["id"] for u in client.get(f"/api/boards/{bid}/members").json()["available"]}
    assert guinea_id in before, "the test user was not invitable to begin with"
    with _deactivated(client, admin_id, guinea_id):
        after = {u["id"] for u in client.get(f"/api/boards/{bid}/members").json()["available"]}
        assert guinea_id not in after


def test_board_invite_is_refused_for_a_deactivated_user(client, admin_id, guinea_id):
    """The dropdown no longer offers them; the endpoint refuses them regardless."""
    bid = _board(client, admin_id)
    with _deactivated(client, admin_id, guinea_id):
        r = _invite(client, bid, admin_id, guinea_id)
        assert r.status_code == 400, r.text
        assert "מושבת" in r.json()["detail"]
    assert guinea_id not in {m["user_id"] for m in
                             client.get(f"/api/boards/{bid}/members").json()["members"]}


def test_workspace_invite_is_refused_for_a_deactivated_user(client, admin_id, guinea_id):
    with _deactivated(client, admin_id, guinea_id):
        avail = {u["id"] for u in client.get("/api/workspace/members").json()["available"]}
        assert guinea_id not in avail
        r = client.post("/api/workspace/members",
                        json={"actor_id": admin_id, "user_id": guinea_id, "role": "member"})
        assert r.status_code == 400, r.text


def test_environment_invite_is_refused_for_a_deactivated_user(client, admin_id, guinea_id):
    envs = client.get(f"/api/environments?actor_id={admin_id}").json()
    env_id = (envs[0]["id"] if isinstance(envs, list) else envs["environments"][0]["id"])
    with _deactivated(client, admin_id, guinea_id):
        d = client.get(f"/api/environments/{env_id}/members?actor_id={admin_id}").json()
        assert guinea_id not in {u["id"] for u in d["available"]}
        r = client.post(f"/api/environments/{env_id}/members",
                        json={"actor_id": admin_id, "user_id": guinea_id, "role": "member"})
        assert r.status_code == 400, r.text


# ── what the pickers are built from ─────────────────────────────────────────

def test_board_payload_leaves_out_a_deactivated_member(client, admin_id, guinea_id):
    """`members` is what the people pickers and the @-menu render."""
    bid = _board(client, admin_id)
    assert _invite(client, bid, admin_id, guinea_id).status_code == 200
    assert guinea_id in {m["id"] for m in _get(client, bid, admin_id)["members"]}
    with _deactivated(client, admin_id, guinea_id):
        assert guinea_id not in {m["id"] for m in _get(client, bid, admin_id)["members"]}


def test_members_screen_still_shows_them_and_says_so(client, admin_id, guinea_id):
    """The board's own members screen must keep listing them — somebody has to be
    able to see the member and take them off the board."""
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, guinea_id)
    with _deactivated(client, admin_id, guinea_id):
        row = next(m for m in client.get(f"/api/boards/{bid}/members").json()["members"]
                   if m["user_id"] == guinea_id)
        assert row["is_active"] is False


# ── tagging ─────────────────────────────────────────────────────────────────

def test_cannot_assign_a_deactivated_member(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, guinea_id)
    tid = _task(client, bid, admin_id)["id"]
    with _deactivated(client, admin_id, guinea_id):
        r = _assign(client, tid, guinea_id, admin_id)
        assert r.status_code == 403, r.text
        assert "מושבת" in r.json()["detail"], "the refusal blamed board membership"
    assert not _get(client, bid, admin_id)["tasks"][0]["assignees"]


def test_an_assignment_made_before_can_still_be_removed(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, guinea_id)
    tid = _task(client, bid, admin_id)["id"]
    assert _assign(client, tid, guinea_id, admin_id).status_code == 200
    with _deactivated(client, admin_id, guinea_id):
        r = _assign(client, tid, guinea_id, admin_id, action="remove")
        assert r.status_code == 200, r.text
        assert guinea_id not in [a["id"] for a in r.json()["assignees"]]


def _people_col(client, bid, admin_id):
    cols = _get(client, bid, admin_id)["columns"] + [{"id": "ppl", "type": "people", "title": "אנשים"}]
    client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": cols})


def test_people_column_drops_a_deactivated_member(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, guinea_id)
    _people_col(client, bid, admin_id)
    tid = _task(client, bid, admin_id)["id"]
    with _deactivated(client, admin_id, guinea_id):
        r = client.patch(f"/api/tasks/{tid}",
                         json={"user_id": admin_id, "custom_fields": {"ppl": [guinea_id]}})
        assert r.status_code == 200, r.text
        stored = _get(client, bid, admin_id)["tasks"][0]["custom_fields"].get("ppl") or []
        assert guinea_id not in stored


def test_people_column_keeps_a_value_written_while_the_account_was_live(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, guinea_id)
    _people_col(client, bid, admin_id)
    tid = _task(client, bid, admin_id)["id"]
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "custom_fields": {"ppl": [guinea_id]}})
    with _deactivated(client, admin_id, guinea_id):
        r = client.patch(f"/api/tasks/{tid}",
                         json={"user_id": admin_id, "custom_fields": {"ppl": [guinea_id]}})
        assert r.status_code == 200, r.text
        assert _get(client, bid, admin_id)["tasks"][0]["custom_fields"].get("ppl") == [guinea_id]


def test_create_task_ignores_a_deactivated_assignee(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, guinea_id)
    with _deactivated(client, admin_id, guinea_id):
        t = _task(client, bid, admin_id, assignee_ids=[guinea_id])
        assert [a["id"] for a in (t.get("assignees") or [])] == []


def test_a_deactivated_member_cannot_be_mentioned(client, admin_id, guinea_id):
    """Typing "@Name" bypasses the picker, so the comment endpoint filters too."""
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, guinea_id)
    tid = _task(client, bid, admin_id)["id"]
    name = next(u["name"] for u in client.get("/api/users").json() if u["id"] == guinea_id)
    with _deactivated(client, admin_id, guinea_id):
        r = client.post(f"/api/tasks/{tid}/comments",
                        json={"actor_id": admin_id, "content": f"שלום @{name}",
                              "mentions": [guinea_id]})
        assert r.status_code == 200, r.text
    posted = client.get(f"/api/tasks/{tid}/comments").json()["comments"][0]
    assert guinea_id not in (posted.get("mentions") or [])


# ── per-user overrides are a grant too ──────────────────────────────────────

def test_item_permission_cannot_be_granted_to_a_deactivated_user(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, guinea_id)
    tid = _task(client, bid, admin_id)["id"]
    with _deactivated(client, admin_id, guinea_id):
        r = client.post(f"/api/tasks/{tid}/permissions",
                        json={"actor_id": admin_id, "user_id": guinea_id, "perm": "edit"})
        assert r.status_code == 400, r.text


def test_an_override_granted_before_can_still_be_cleared(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, guinea_id)
    tid = _task(client, bid, admin_id)["id"]
    client.post(f"/api/tasks/{tid}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "edit"})
    with _deactivated(client, admin_id, guinea_id):
        r = client.post(f"/api/tasks/{tid}/permissions",
                        json={"actor_id": admin_id, "user_id": guinea_id, "perm": None})
        assert r.status_code == 200, r.text
        assert str(guinea_id) not in (r.json()["permissions"] or {})


# ── automations name a person too ───────────────────────────────────────────

def test_a_rule_cannot_be_stored_naming_a_deactivated_person(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _invite(client, bid, admin_id, guinea_id, role="admin")
    with _deactivated(client, admin_id, guinea_id):
        r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                        json={"recipe_id": "created_notify_person",
                              "config": {"a_person": guinea_id}, "is_active": True})
        assert r.status_code == 400, r.text
        assert "מושבת" in r.json()["detail"]
