"""Permissions on the connect column: what a user may search, see and link.

The rule under test, in one line: a connect column may never become a way to
learn something you could not have learned by opening the other board yourself.
Seeing a link is not permission to open what it points at.
"""

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _cell(client, tid, col_id, uid):
    t = client.get(f"/api/tasks/{tid}", headers=AS(uid)).json()
    return (t.get("custom_fields") or {}).get(col_id) or []


def _setup(client, admin_id, outsider, tag, two_way=True):
    """Board `open` (outsider is an editor) with a connect column to `closed`
    (outsider is not a member at all)."""
    a, b = _board(client, admin_id, f"פתוח {tag}"), _board(client, admin_id, f"סגור {tag}")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": outsider, "role": "editor"})
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True,
                                            "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    return a, b, next(c for c in _cols(client, a) if c["type"] == "connect")


# ── searching ───────────────────────────────────────────────────────────────

def test_a_board_you_cannot_see_yields_no_items(client, admin_id, guinea_id):
    a, b, col = _setup(client, admin_id, guinea_id, "s1")
    _item(client, b, admin_id, "פריט חסוי")
    r = client.get(f"/api/items/search?board_ids={b}", headers=AS(guinea_id)).json()
    assert r["items"] == [] and r["total"] == 0


def test_an_empty_board_list_searches_nothing_not_everything(client, admin_id, guinea_id):
    """The picker always names its target boards. A blank list used to fall back
    to every board the caller could see, so dropping the parameter turned a
    column scoped to one board into a workspace-wide search."""
    a, b, col = _setup(client, admin_id, guinea_id, "s2")
    _item(client, a, admin_id, "פריט גלוי s2")
    r = client.get("/api/items/search?board_ids=", headers=AS(guinea_id)).json()
    assert r["items"] == [] and r["total"] == 0


def test_a_visible_board_still_returns_its_items(client, admin_id, guinea_id):
    a, b, col = _setup(client, admin_id, guinea_id, "s3")
    t = _item(client, a, admin_id, "פריט גלוי s3")
    r = client.get(f"/api/items/search?board_ids={a}", headers=AS(guinea_id)).json()
    assert t in [x["id"] for x in r["items"]], "the restriction swallowed a legitimate result"


def test_an_item_closed_to_you_individually_is_not_in_the_results(client, admin_id, guinea_id):
    """Board access is not item access: an item on a board you belong to can
    still carry a per-user override that shuts you out."""
    a, b, col = _setup(client, admin_id, guinea_id, "s4")
    t = _item(client, a, admin_id, "פריט חסום s4")
    client.post(f"/api/tasks/{t}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"})
    mine = client.get(f"/api/items/search?board_ids={a}", headers=AS(guinea_id)).json()
    theirs = client.get(f"/api/items/search?board_ids={a}", headers=AS(admin_id)).json()
    assert t not in [x["id"] for x in mine["items"]]
    assert t in [x["id"] for x in theirs["items"]], "the override leaked onto everyone"
    assert mine["total"] == theirs["total"] - 1, "total must count what is actually returned"


# ── resolving ids to titles ─────────────────────────────────────────────────

def test_lookup_will_not_turn_a_hidden_id_into_a_title(client, admin_id, guinea_id):
    a, b, col = _setup(client, admin_id, guinea_id, "l1")
    t = _item(client, b, admin_id, "כותרת חסויה")
    got = client.get(f"/api/tasks/lookup?ids={t}", headers=AS(guinea_id)).json()["items"]
    assert [x["id"] for x in got] == [t]
    entry = got[0]
    assert entry.get("restricted") is True
    assert not entry.get("title") and not entry.get("board_name") and not entry.get("board_id")


def test_lookup_still_resolves_what_you_may_see(client, admin_id, guinea_id):
    a, b, col = _setup(client, admin_id, guinea_id, "l2")
    t = _item(client, a, admin_id, "כותרת גלויה")
    entry = client.get(f"/api/tasks/lookup?ids={t}", headers=AS(guinea_id)).json()["items"][0]
    assert entry["title"] == "כותרת גלויה" and entry["board_id"] == a


# ── what the cell hands out ─────────────────────────────────────────────────

def test_the_cell_hides_links_pointing_where_you_cannot_go(client, admin_id, guinea_id):
    a, b, col = _setup(client, admin_id, guinea_id, "c1")
    mine, hidden = _item(client, a, admin_id, "שלי c1"), _item(client, b, admin_id, "חסוי c1")
    client.patch(f"/api/tasks/{mine}?user_id={admin_id}",
                 json={"custom_fields": {col["id"]: [hidden]}})
    assert _cell(client, mine, col["id"], admin_id) == [hidden]
    assert _cell(client, mine, col["id"], guinea_id) == [], "the id of a hidden item was handed out"


def test_the_mirror_side_is_hidden_too(client, admin_id, guinea_id):
    """The reverse of a two-way link lives on the other board — the same rule
    has to hold when you are reading it from that side."""
    a, b, col = _setup(client, admin_id, guinea_id, "c2")
    mirror = col["connect"]["mirror"][str(b)]
    mine, theirs = _item(client, a, admin_id, "שלי c2"), _item(client, b, admin_id, "שלהם c2")
    client.patch(f"/api/tasks/{mine}?user_id={admin_id}",
                 json={"custom_fields": {col["id"]: [theirs]}})
    assert _cell(client, theirs, mirror, admin_id) == [mine]
    r = client.get(f"/api/tasks/{theirs}", headers=AS(guinea_id))
    assert r.status_code == 403, "the outsider could open the item on the closed board"


def test_a_one_way_column_hides_them_as_well(client, admin_id, guinea_id):
    a, b, col = _setup(client, admin_id, guinea_id, "c3", two_way=False)
    mine, hidden = _item(client, a, admin_id, "שלי c3"), _item(client, b, admin_id, "חסוי c3")
    client.patch(f"/api/tasks/{mine}?user_id={admin_id}",
                 json={"custom_fields": {col["id"]: [hidden]}})
    assert _cell(client, mine, col["id"], guinea_id) == []
    assert _cell(client, mine, col["id"], admin_id) == [hidden]


# ── writing ─────────────────────────────────────────────────────────────────

def test_you_cannot_link_to_an_item_you_cannot_see(client, admin_id, guinea_id):
    """Otherwise the picker's restrictions are decoration: post the id instead."""
    a, b, col = _setup(client, admin_id, guinea_id, "w1")
    mine, theirs = _item(client, a, admin_id, "שלי w1"), _item(client, b, admin_id, "שלהם w1")
    client.patch(f"/api/tasks/{mine}?user_id={guinea_id}",
                 json={"custom_fields": {col["id"]: [theirs]}}, headers=AS(guinea_id))
    assert _cell(client, mine, col["id"], admin_id) == [], "a link was planted on a closed board"


def test_the_same_holds_for_a_one_way_column(client, admin_id, guinea_id):
    a, b, col = _setup(client, admin_id, guinea_id, "w2", two_way=False)
    mine, theirs = _item(client, a, admin_id, "שלי w2"), _item(client, b, admin_id, "שלהם w2")
    client.patch(f"/api/tasks/{mine}?user_id={guinea_id}",
                 json={"custom_fields": {col["id"]: [theirs]}}, headers=AS(guinea_id))
    assert _cell(client, mine, col["id"], admin_id) == []


def test_saving_a_cell_does_not_delete_the_links_you_were_never_shown(client, admin_id, guinea_id):
    """The other half of hiding them. The outsider's cell renders empty, so if a
    plain save meant "this is the whole list", editing anything on that item
    would quietly destroy links they had no idea existed."""
    a, b, col = _setup(client, admin_id, guinea_id, "w3")
    mine, hidden = _item(client, a, admin_id, "שלי w3"), _item(client, b, admin_id, "חסוי w3")
    visible = _item(client, a, admin_id, "גלוי w3")
    client.patch(f"/api/tasks/{mine}?user_id={admin_id}",
                 json={"custom_fields": {col["id"]: [hidden]}})
    client.patch(f"/api/tasks/{mine}?user_id={guinea_id}",
                 json={"custom_fields": {col["id"]: []}}, headers=AS(guinea_id))
    assert hidden in _cell(client, mine, col["id"], admin_id), "a link the actor could not see was deleted"


def test_a_user_can_still_manage_the_links_they_can_see(client, admin_id, guinea_id):
    """Preserving hidden links must not freeze the cell for everyone else."""
    a, b, col = _setup(client, admin_id, guinea_id, "w4")
    # let the outsider onto the target board so its items are legitimately linkable
    client.post(f"/api/boards/{b}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    mine, one, two = (_item(client, a, admin_id, "שלי w4"),
                      _item(client, b, admin_id, "אחד w4"), _item(client, b, admin_id, "שתיים w4"))
    client.patch(f"/api/tasks/{mine}?user_id={guinea_id}",
                 json={"custom_fields": {col["id"]: [one, two]}}, headers=AS(guinea_id))
    assert sorted(_cell(client, mine, col["id"], guinea_id)) == sorted([one, two])
    client.patch(f"/api/tasks/{mine}?user_id={guinea_id}",
                 json={"custom_fields": {col["id"]: [one]}}, headers=AS(guinea_id))
    assert _cell(client, mine, col["id"], guinea_id) == [one], "a removal the user was allowed to make did not stick"
