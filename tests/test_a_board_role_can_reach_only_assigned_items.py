"""Two board roles whose reach is the items they are assigned to.

Until now a board role was all-or-nothing about items: an editor could edit every
row, a viewer could read every row. Two roles narrow that to the person's own
work:

* `assigned_editor` sees every item on the board and edits only the ones they
  are assigned to — the rest are read-only for them.
* `assigned_only` sees and edits ONLY the items they are assigned to. Every
  other item does not exist for them: not on the board, not in its count, not in
  the paged query, not in the link picker's search, not in the board's log and
  not in their bell.

"Assigned" means named in the board's permission column (the built-in assignees
unless the board says otherwise — see
test_the_permission_column_decides_who_is_assigned.py), and a sub-item follows
its parent. A per-user override on the item (POST /api/tasks/{id}/permissions)
still wins over all of it, exactly as it wins over every other role.

At board level both roles rank as a viewer: they add no items, no groups and no
columns. The whole point of the role is that their work is handed to them.

What makes this worth pinning in many places at once is that "which items can
this person reach" is answered separately by every one of those routes. One of
them forgetting the new role is a leak of exactly the rows the role exists to
hide — and it would look fine on every other route.
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


def _assign(client, admin_id, tid, uid, action="add"):
    r = client.post(f"/api/tasks/{tid}/assignees", headers=AS(admin_id),
                    json={"user_id": uid, "action": action})
    assert r.status_code == 200, r.text
    return r


def _item(client, admin_id, bid, title, **extra):
    r = client.post("/api/tasks", headers=AS(admin_id),
                    json={"board_id": bid, "title": title, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _board_json(client, bid, uid):
    r = client.get(f"/api/boards/{bid}", headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _rows(client, bid, uid):
    """{id: my_perm} for the top-level rows this reader is sent."""
    return {t["id"]: t.get("my_perm") for t in _board_json(client, bid, uid)["tasks"]
            if not t.get("parent_id")}


@pytest.fixture
def ae(client, admin_id):
    return _user(client, admin_id, "בודק עורך משויכים", "test.assigned.editor@cityos.test")


@pytest.fixture
def ao(client, admin_id):
    return _user(client, admin_id, "בודק משויכים בלבד", "test.assigned.only@cityos.test")


@pytest.fixture
def board(client, admin_id, ae, ao):
    """A board with one item for each role-holder and one nobody is on.

    Deleting the board at the end takes the items, their overrides, their
    comments and the memberships with it — everything these tests touch.
    """
    r = client.post("/api/boards", headers=AS(admin_id), json={"name": "לוח משויכים"})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        for uid, role in ((ae, "assigned_editor"), (ao, "assigned_only")):
            r = client.post(f"/api/boards/{bid}/members", headers=AS(admin_id),
                            json={"user_id": uid, "role": role})
            assert r.status_code == 200, r.text
        mine_ae = _item(client, admin_id, bid, "של העורך")
        mine_ao = _item(client, admin_id, bid, "של המשויך")
        nobody = _item(client, admin_id, bid, "של אף אחד")
        _assign(client, admin_id, mine_ae, ae)
        _assign(client, admin_id, mine_ao, ao)
        yield {"id": bid, "mine_ae": mine_ae, "mine_ao": mine_ao, "nobody": nobody}
    finally:
        client.delete(f"/api/boards/{bid}", headers=AS(admin_id))


# ── the roles exist ───────────────────────────────────────────────────────

def test_both_new_roles_are_accepted_when_inviting_and_when_changing_a_role(
        client, admin_id, ae, ao, board):
    bid = board["id"]
    roles = {m["user_id"]: m["role"] for m in
             client.get(f"/api/boards/{bid}/members", headers=AS(admin_id)).json()["members"]}
    assert roles.get(ae) == "assigned_editor", roles
    assert roles.get(ao) == "assigned_only", roles

    r = client.patch(f"/api/boards/{bid}/members/{ae}", headers=AS(admin_id),
                     json={"role": "assigned_only"})
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/boards/{bid}/members/{ao}", headers=AS(admin_id),
                     json={"role": "assigned_editor"})
    assert r.status_code == 200, r.text
    roles = {m["user_id"]: m["role"] for m in
             client.get(f"/api/boards/{bid}/members", headers=AS(admin_id)).json()["members"]}
    assert roles.get(ae) == "assigned_only" and roles.get(ao) == "assigned_editor", roles


def test_the_boards_own_member_list_says_what_role_each_member_has(client, admin_id, ae, ao, board):
    """The pickers draw from the board payload's members[], and the browser
    needs the role there to know who an @mention could even reach."""
    members = {m["id"]: m for m in _board_json(client, board["id"], admin_id)["members"]}
    assert members[ae].get("role") == "assigned_editor", members[ae]
    assert members[ao].get("role") == "assigned_only", members[ao]


def test_an_unknown_role_is_refused_on_invite_and_on_change(client, admin_id, ae, board):
    """It used to be quietly turned into "editor" — a typo in a role name
    granted edit over every item, the opposite of what was being asked for."""
    bid = board["id"]
    r = client.post(f"/api/boards/{bid}/members", headers=AS(admin_id),
                    json={"user_id": ae, "role": "assigned_superuser"})
    assert r.status_code == 400, r.text
    r = client.patch(f"/api/boards/{bid}/members/{ae}", headers=AS(admin_id),
                     json={"role": "assigned_superuser"})
    assert r.status_code == 400, r.text
    roles = {m["user_id"]: m["role"] for m in
             client.get(f"/api/boards/{bid}/members", headers=AS(admin_id)).json()["members"]}
    assert roles.get(ae) == "assigned_editor", "a refused role still changed the member"


# ── what each role is told it may do, item by item ───────────────────────

def test_an_assigned_editor_sees_every_item_and_may_edit_only_their_own(client, ae, board):
    rows = _rows(client, board["id"], ae)
    assert rows.get(board["mine_ae"]) == "edit", rows
    assert rows.get(board["nobody"]) == "view", rows
    assert rows.get(board["mine_ao"]) == "view", rows


def test_an_assigned_only_member_is_sent_their_own_items_and_nothing_else(client, ao, board):
    rows = _rows(client, board["id"], ao)
    assert set(rows) == {board["mine_ao"]}, rows
    assert rows[board["mine_ao"]] == "edit", rows


def test_the_count_the_paged_query_and_the_search_all_agree_for_assigned_only(client, ao, board):
    """Four routes answer "what is on this board for me" — they must give the
    same answer, or the hidden rows leak through whichever one forgot."""
    bid = board["id"]
    b = _board_json(client, bid, ao)
    assert b["item_count"] == 1, b["item_count"]

    r = client.post(f"/api/boards/{bid}/items/query", headers=AS(ao),
                    json={"filter": {"operator": "and", "rules": []}, "ids_only": True})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1, r.json()["total"]
    assert set(r.json()["item_ids"]) == {board["mine_ao"]}, r.json()["item_ids"]

    r = client.post(f"/api/boards/{bid}/items/query", headers=AS(ao),
                    json={"filter": {"operator": "and", "rules": []}})
    assert r.status_code == 200, r.text
    paged = {t["id"] for t in r.json()["items"]}
    assert board["nobody"] not in paged and board["mine_ae"] not in paged, paged

    r = client.get("/api/items/search", headers=AS(ao), params={"board_ids": str(bid)})
    assert r.status_code == 200, r.text
    found = {it["id"] for it in r.json()["items"]}
    assert found == {board["mine_ao"]}, found


def test_the_admin_still_counts_every_item_on_the_same_board(client, admin_id, board):
    """The narrowing is of the reader, not of the board."""
    rows = _rows(client, board["id"], admin_id)
    assert {board["mine_ae"], board["mine_ao"], board["nobody"]} <= set(rows)
    assert _board_json(client, board["id"], admin_id)["item_count"] == len(rows)


def test_an_item_assigned_only_cannot_see_cannot_be_opened_or_touched_directly(client, ao, board):
    """Knowing an item's id is not a way round the board hiding it."""
    hidden = board["nobody"]
    assert client.get(f"/api/tasks/{hidden}", headers=AS(ao)).status_code in (403, 404)
    r = client.patch(f"/api/tasks/{hidden}", headers=AS(ao), json={"title": "נפרץ"})
    assert r.status_code in (403, 404), r.text
    r = client.post(f"/api/tasks/{hidden}/comments", headers=AS(ao), json={"content": "שלום"})
    assert r.status_code in (403, 404), r.text


# ── board level: both rank as a viewer ───────────────────────────────────

@pytest.mark.parametrize("who", ["ae", "ao"])
def test_neither_role_may_add_an_item_a_group_or_a_column(client, admin_id, board, who, request):
    uid = request.getfixturevalue(who)
    bid = board["id"]
    r = client.post("/api/tasks", headers=AS(uid), json={"board_id": bid, "title": "חדש"})
    assert r.status_code == 403, r.text
    r = client.post("/api/groups", headers=AS(uid), json={"board_id": bid, "name": "קבוצה"})
    assert r.status_code == 403, r.text
    cols = _board_json(client, bid, admin_id)["columns"]
    r = client.patch(f"/api/boards/{bid}", headers=AS(uid),
                     json={"columns": cols + [{"id": "extra", "type": "text", "title": "עוד"}]})
    assert r.status_code == 403, r.text


# ── editing and commenting ───────────────────────────────────────────────

def test_an_assigned_editor_edits_and_comments_on_an_assigned_item(client, ae, board):
    tid = board["mine_ae"]
    r = client.patch(f"/api/tasks/{tid}", headers=AS(ae), json={"title": "עודכן ע\"י העורך"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/tasks/{tid}/comments", headers=AS(ae), json={"content": "עבדתי על זה"})
    assert r.status_code == 200, r.text


def test_an_assigned_editor_cannot_edit_or_comment_on_an_item_they_are_not_on(client, ae, board):
    for tid in (board["nobody"], board["mine_ao"]):
        r = client.patch(f"/api/tasks/{tid}", headers=AS(ae), json={"title": "לא שלי"})
        assert r.status_code == 403, r.text
        r = client.post(f"/api/tasks/{tid}/comments", headers=AS(ae), json={"content": "לא שלי"})
        assert r.status_code == 403, r.text


def test_an_assigned_only_member_edits_and_comments_on_their_own_item(client, ao, board):
    tid = board["mine_ao"]
    r = client.patch(f"/api/tasks/{tid}", headers=AS(ao), json={"title": "עודכן ע\"י המשויך"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/tasks/{tid}/comments", headers=AS(ao), json={"content": "בטיפול"})
    assert r.status_code == 200, r.text


def test_taking_someone_off_an_item_takes_their_reach_with_it(client, admin_id, ao, ae, board):
    tid = board["mine_ao"]
    _assign(client, admin_id, tid, ao, action="remove")
    assert tid not in _rows(client, board["id"], ao)
    _assign(client, admin_id, tid, ae)
    assert _rows(client, board["id"], ae).get(tid) == "edit"


# ── the override still wins ──────────────────────────────────────────────

def test_a_per_item_override_still_wins_over_the_assignment(client, admin_id, ae, ao, board):
    bid = board["id"]

    def override(tid, uid, perm):
        r = client.post(f"/api/tasks/{tid}/permissions", headers=AS(admin_id),
                        json={"user_id": uid, "perm": perm})
        assert r.status_code == 200, r.text

    # closed to them although they are on it
    override(board["mine_ae"], ae, "none")
    assert board["mine_ae"] not in _rows(client, bid, ae)
    # opened to them although they are not on it
    override(board["nobody"], ae, "edit")
    assert _rows(client, bid, ae).get(board["nobody"]) == "edit"
    r = client.patch(f"/api/tasks/{board['nobody']}", headers=AS(ae), json={"title": "פתוח בהחרגה"})
    assert r.status_code == 200, r.text
    # an unassigned item shown to assigned_only by an override, read-only
    override(board["nobody"], ao, "view")
    assert _rows(client, bid, ao).get(board["nobody"]) == "view"
    r = client.patch(f"/api/tasks/{board['nobody']}", headers=AS(ao), json={"title": "לא"})
    assert r.status_code == 403, r.text

    # clearing the overrides puts the assignment back in charge
    override(board["mine_ae"], ae, None)
    override(board["nobody"], ae, None)
    override(board["nobody"], ao, None)
    rows = _rows(client, bid, ae)
    assert rows.get(board["mine_ae"]) == "edit" and rows.get(board["nobody"]) == "view", rows
    assert board["nobody"] not in _rows(client, bid, ao)


# ── a sub-item follows its parent ────────────────────────────────────────

def test_a_sub_item_follows_its_parent(client, admin_id, ae, ao, board):
    """Nobody assigns a sub-item separately to the person who owns the item —
    the parent's assignment is what reaches it."""
    sub_ae = _item(client, admin_id, board["id"], "תת של העורך", parent_id=board["mine_ae"])
    sub_ao = _item(client, admin_id, board["id"], "תת של המשויך", parent_id=board["mine_ao"])
    sub_none = _item(client, admin_id, board["id"], "תת של אף אחד", parent_id=board["nobody"])

    def perm(tid, uid):
        r = client.get(f"/api/tasks/{tid}", headers=AS(uid))
        return r.json().get("my_perm") if r.status_code == 200 else r.status_code

    assert perm(sub_ae, ae) == "edit"
    assert perm(sub_none, ae) == "view"
    assert perm(sub_ao, ao) == "edit"
    assert perm(sub_none, ao) in (403, 404)
    assert perm(sub_ae, ao) in (403, 404)

    assert client.patch(f"/api/tasks/{sub_ae}", headers=AS(ae),
                        json={"title": "תת עודכן"}).status_code == 200
    assert client.patch(f"/api/tasks/{sub_none}", headers=AS(ae),
                        json={"title": "לא"}).status_code == 403
    assert client.patch(f"/api/tasks/{sub_ao}", headers=AS(ao),
                        json={"title": "תת עודכן"}).status_code == 200
    assert client.patch(f"/api/tasks/{sub_none}", headers=AS(ao),
                        json={"title": "לא"}).status_code in (403, 404)


# ── the log and the bell ─────────────────────────────────────────────────

def test_the_board_log_holds_no_line_about_an_item_assigned_only_cannot_see(
        client, admin_id, ao, board):
    bid = board["id"]
    for tid in (board["mine_ao"], board["nobody"], board["mine_ae"]):
        r = client.patch(f"/api/tasks/{tid}", headers=AS(admin_id), json={"title": f"שם חדש {tid}"})
        assert r.status_code == 200, r.text
    r = client.get(f"/api/boards/{bid}/activity", headers=AS(ao))
    assert r.status_code == 200, r.text
    about = {row.get("task_id") for row in r.json()["activity"]}
    assert board["mine_ao"] in about, "the log lost their own item too — nothing is being shown"
    assert board["nobody"] not in about, "the log names an item hidden from them"
    assert board["mine_ae"] not in about, "the log names an item hidden from them"
    titles = " ".join(str(row.get("task_title")) for row in r.json()["activity"])
    assert f"שם חדש {board['nobody']}" not in titles


def test_the_bell_holds_nothing_about_an_item_they_can_no_longer_see(client, admin_id, ao, board):
    """Being assigned rings the bell; being taken off the item again must take
    the item out of their bell along with everything else."""
    tid = board["nobody"]
    _assign(client, admin_id, tid, ao)
    _assign(client, admin_id, tid, ao, action="remove")
    r = client.get("/api/notifications?limit=200", headers=AS(ao))
    assert r.status_code == 200, r.text
    about = {n.get("task_id") for n in r.json()["notifications"]}
    assert board["mine_ao"] in about, "no notification at all — the test proves nothing"
    assert tid not in about, "the bell still shows an item they cannot see"
