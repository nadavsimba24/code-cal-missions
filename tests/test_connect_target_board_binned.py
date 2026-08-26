"""The target board goes to the recycle bin.

The items on it were never deleted, but they are not reachable, so a link to
one must not stay an active-looking reference. Same policy as a binned item:
marked rather than dropped, because the board comes back with its items and the
relationship rows were never touched.
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


def _set(client, tid, col_id, ids, uid):
    return client.patch(f"/api/tasks/{tid}?user_id={uid}",
                        json={"custom_fields": {col_id: ids}}, headers=AS(uid))


def _look(client, tid, uid):
    return client.get(f"/api/tasks/lookup?ids={tid}", headers=AS(uid)).json()["items"][0]


def _setup(client, admin_id, tag, two_way=True):
    a, b = _board(client, admin_id, f"מקור {tag}"), _board(client, admin_id, f"יעד {tag}")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    return a, b, next(x for x in _cols(client, a) if x["type"] == "connect")


# ── nothing new may point at it ─────────────────────────────────────────────

def test_the_picker_does_not_offer_a_binned_board(client, admin_id):
    a, b, c = _setup(client, admin_id, "n1")
    _item(client, b, admin_id, "יעד")
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    assert client.get(f"/api/items/search?board_ids={b}", headers=AS(admin_id)).json()["items"] == []


def test_no_new_link_can_be_made_to_a_binned_board(client, admin_id):
    """Board membership survives the bin, so the permission check alone said
    yes — the board being in the bin is what has to say no."""
    a, b, c = _setup(client, admin_id, "n2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    _set(client, src, c["id"], [x], admin_id)
    assert _cell(client, src, c["id"], admin_id) == []


def test_the_same_for_a_one_way_column(client, admin_id):
    a, b, c = _setup(client, admin_id, "n3", two_way=False)
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    _set(client, src, c["id"], [x], admin_id)
    assert _cell(client, src, c["id"], admin_id) == []


# ── existing ones are marked, and say which bin ─────────────────────────────

def test_an_existing_link_is_marked_rather_than_left_active(client, admin_id):
    a, b, c = _setup(client, admin_id, "m1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    e = _look(client, x, admin_id)
    assert e["deleted"] is True
    assert e["deleted_scope"] == "board", "the reader cannot tell what to restore"


def test_a_binned_item_still_reports_the_item_scope(client, admin_id):
    """The two are different jobs to fix, so they must not collapse into one."""
    a, b, c = _setup(client, admin_id, "m2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/tasks/{x}?user_id={admin_id}")
    e = _look(client, x, admin_id)
    assert e["deleted"] is True and e["deleted_scope"] == "item"


def test_the_item_cannot_be_opened_while_its_board_is_binned(client, admin_id):
    a, b, c = _setup(client, admin_id, "m3")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    for door in ("", "/comments", "/files", "/activity"):
        r = client.get(f"/api/tasks/{x}{door}", headers=AS(admin_id))
        assert r.status_code in (403, 404), f"{door} → {r.status_code}"


# ── and they come back ──────────────────────────────────────────────────────

def test_restoring_the_board_restores_the_links(client, admin_id):
    a, b, c = _setup(client, admin_id, "r1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    client.post(f"/api/trash/boards/{b}/restore", json={"user_id": admin_id})
    assert _cell(client, src, c["id"], admin_id) == [x]
    e = _look(client, x, admin_id)
    assert e["deleted"] is False and e["title"] == "יעד"


def test_the_mirror_comes_back_too(client, admin_id):
    a, b, c = _setup(client, admin_id, "r2")
    mirror = c["connect"]["mirror"][str(b)]
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    client.post(f"/api/trash/boards/{b}/restore", json={"user_id": admin_id})
    assert _cell(client, x, mirror, admin_id) == [src]


def test_editing_the_cell_while_the_board_is_binned_keeps_the_link(client, admin_id):
    a, b, c = _setup(client, admin_id, "r3")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    _set(client, src, c["id"], [x], admin_id)          # the client sends back what it was shown
    client.post(f"/api/trash/boards/{b}/restore", json={"user_id": admin_id})
    assert _cell(client, src, c["id"], admin_id) == [x], "the link was lost while the board sat in the bin"


def test_purging_the_board_leaves_no_reference_at_all(client, admin_id):
    a, b, c = _setup(client, admin_id, "r4")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    client.delete(f"/api/trash/boards/{b}?user_id={admin_id}")
    assert _cell(client, src, c["id"], admin_id) == []
    assert _look(client, x, admin_id).get("restricted") is True
