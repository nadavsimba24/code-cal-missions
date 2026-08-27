"""Managing links that already exist: add, remove, replace, several at once.

And the line that governs all of them — changing a link changes the reference
and nothing else. Neither the item holding the link nor the item it points at
has its content touched.
"""

AS = lambda uid: {"X-CityOS-User": str(uid)}
_CONTENT = ("title", "description", "status", "priority", "due_date",
            "group_id", "position", "assignees")


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


def _set(client, tid, col_id, ids, uid):
    return client.patch(f"/api/tasks/{tid}?user_id={uid}",
                        json={"custom_fields": {col_id: ids}}, headers=AS(uid))


def _setup(client, admin_id, tag, multiple=True, two_way=True):
    a, b = _board(client, admin_id, f"מקור {tag}"), _board(client, admin_id, f"יעד {tag}")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": multiple,
                                            "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    return a, b, next(c for c in _cols(client, a) if c["type"] == "connect")


def _content(client, tid, admin_id):
    t = client.get(f"/api/tasks/{tid}", headers=AS(admin_id)).json()
    return {k: t.get(k) for k in _CONTENT}


# ── the four operations ─────────────────────────────────────────────────────

def test_an_editor_can_add_a_link(client, admin_id):
    a, b, c = _setup(client, admin_id, "e1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    assert _cell(client, src, c["id"], admin_id) == [x]


def test_an_editor_can_remove_a_link(client, admin_id):
    a, b, c = _setup(client, admin_id, "e2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [], admin_id)
    assert _cell(client, src, c["id"], admin_id) == []
    assert _cell(client, x, c["connect"]["mirror"][str(b)], admin_id) == [], "the reverse survived"


def test_replacing_swaps_the_reference(client, admin_id):
    a, b, c = _setup(client, admin_id, "e3", multiple=False)
    src = _item(client, a, admin_id, "מקור")
    x, y = _item(client, b, admin_id, "ראשון"), _item(client, b, admin_id, "שני")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [y], admin_id)
    assert _cell(client, src, c["id"], admin_id) == [y]
    assert _cell(client, x, c["connect"]["mirror"][str(b)], admin_id) == [], "the replaced end kept its link"


def test_a_multiple_column_takes_several_and_gives_them_back(client, admin_id):
    a, b, c = _setup(client, admin_id, "e4", multiple=True)
    src = _item(client, a, admin_id, "מקור")
    ids = [_item(client, b, admin_id, f"יעד {i}") for i in range(4)]
    _set(client, src, c["id"], ids, admin_id)
    assert sorted(_cell(client, src, c["id"], admin_id)) == sorted(ids)


def test_removing_one_of_several_leaves_the_rest(client, admin_id):
    a, b, c = _setup(client, admin_id, "e5", multiple=True)
    src = _item(client, a, admin_id, "מקור")
    ids = [_item(client, b, admin_id, f"יעד {i}") for i in range(4)]
    _set(client, src, c["id"], ids, admin_id)
    _set(client, src, c["id"], [ids[0], ids[2], ids[3]], admin_id)
    assert sorted(_cell(client, src, c["id"], admin_id)) == sorted([ids[0], ids[2], ids[3]])
    assert _cell(client, ids[1], c["connect"]["mirror"][str(b)], admin_id) == []


# ── cardinality is the column's, not the picker's ───────────────────────────

def test_a_single_link_column_holds_one(client, admin_id):
    """The picker cleared the selection before saving, so the API never had to
    — which meant anything that was not the picker could put a list of any
    length into a column configured for one item."""
    a, b, c = _setup(client, admin_id, "c1", multiple=False)
    src = _item(client, a, admin_id, "מקור")
    x, y = _item(client, b, admin_id, "ראשון"), _item(client, b, admin_id, "שני")
    _set(client, src, c["id"], [x, y], admin_id)
    assert _cell(client, src, c["id"], admin_id) == [y], "a single-link column took both"


def test_a_one_way_single_link_column_holds_one_too(client, admin_id):
    a, b, c = _setup(client, admin_id, "c2", multiple=False, two_way=False)
    src = _item(client, a, admin_id, "מקור")
    x, y = _item(client, b, admin_id, "ראשון"), _item(client, b, admin_id, "שני")
    _set(client, src, c["id"], [x, y], admin_id)
    assert _cell(client, src, c["id"], admin_id) == [y]


def test_clearing_a_single_link_column_still_clears_it(client, admin_id):
    a, b, c = _setup(client, admin_id, "c3", multiple=False)
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [], admin_id)
    assert _cell(client, src, c["id"], admin_id) == []


# ── who may do it ───────────────────────────────────────────────────────────

def test_a_viewer_cannot_add_one(client, admin_id, guinea_id):
    a, b, c = _setup(client, admin_id, "p1")
    for bid in (a, b):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], guinea_id)
    assert _cell(client, src, c["id"], admin_id) == []


def test_a_viewer_cannot_remove_one(client, admin_id, guinea_id):
    a, b, c = _setup(client, admin_id, "p2")
    for bid in (a, b):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [], guinea_id)
    assert _cell(client, src, c["id"], admin_id) == [x]


def test_a_column_set_to_view_only_refuses_the_edit(client, admin_id, member_id):
    """Board-level edit is not enough — the column carries its own permission."""
    a, b, c = _setup(client, admin_id, "p3")
    for bid in (a, b):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    client.post(f"/api/boards/{a}/columns/{c['id']}/permissions",
                json={"actor_id": admin_id, "user_id": member_id, "perm": "view"})
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], member_id)
    assert _cell(client, src, c["id"], admin_id) == []


# ── the reference, and only the reference ───────────────────────────────────

def test_linking_leaves_both_items_alone(client, admin_id):
    a, b, c = _setup(client, admin_id, "r1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.patch(f"/api/tasks/{src}?user_id={admin_id}", json={"description": "תיאור המקור"})
    client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"description": "תיאור היעד"})
    before = (_content(client, src, admin_id), _content(client, x, admin_id))
    other_cols_before = {k: v for k, v in
                         (client.get(f"/api/tasks/{x}", headers=AS(admin_id)).json().get("custom_fields") or {}).items()
                         if k != c["connect"]["mirror"][str(b)]}
    _set(client, src, c["id"], [x], admin_id)
    assert (_content(client, src, admin_id), _content(client, x, admin_id)) == before
    other_cols_after = {k: v for k, v in
                        (client.get(f"/api/tasks/{x}", headers=AS(admin_id)).json().get("custom_fields") or {}).items()
                        if k != c["connect"]["mirror"][str(b)]}
    assert other_cols_after == other_cols_before, "linking wrote into the linked item's other columns"


def test_unlinking_leaves_both_items_alone(client, admin_id):
    a, b, c = _setup(client, admin_id, "r2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    before = (_content(client, src, admin_id), _content(client, x, admin_id))
    _set(client, src, c["id"], [], admin_id)
    assert (_content(client, src, admin_id), _content(client, x, admin_id)) == before


def test_deleting_the_link_does_not_delete_the_item(client, admin_id):
    a, b, c = _setup(client, admin_id, "r3")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [], admin_id)
    assert client.get(f"/api/tasks/{x}", headers=AS(admin_id)).status_code == 200
    assert client.get(f"/api/tasks/{x}", headers=AS(admin_id)).json()["title"] == "יעד"


def test_the_links_come_back_in_the_order_they_were_made(client, admin_id):
    """A two-way cell has nowhere to keep an order of its own — one shared row
    serves both sides — so without an explicit one the same cell comes back
    differently on different loads, and the grid shows a different first name."""
    a, b, c = _setup(client, admin_id, "o1", multiple=True)
    src = _item(client, a, admin_id, "מקור")
    ids = [_item(client, b, admin_id, f"יעד {i}") for i in range(5)]
    _set(client, src, c["id"], ids, admin_id)
    assert _cell(client, src, c["id"], admin_id) == ids
    for _ in range(3):
        assert _cell(client, src, c["id"], admin_id) == ids, "the order is not stable across reads"


def test_a_link_added_later_goes_last(client, admin_id):
    a, b, c = _setup(client, admin_id, "o2", multiple=True)
    src = _item(client, a, admin_id, "מקור")
    first = [_item(client, b, admin_id, f"ראשון {i}") for i in range(2)]
    _set(client, src, c["id"], first, admin_id)
    late = _item(client, b, admin_id, "מאוחר")
    _set(client, src, c["id"], first + [late], admin_id)
    assert _cell(client, src, c["id"], admin_id) == first + [late]
