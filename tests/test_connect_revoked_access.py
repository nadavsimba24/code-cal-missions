"""When the viewer no longer has access to the linked item.

The link must not become a way around the permission that was taken away —
not through the cell, not through the item's own endpoints, and not through
the history, which stores connect values as raw id lists.
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


def _setup(client, admin_id, who, tag):
    """Both boards open to `who`, a two-way connect column between them."""
    a, b = _board(client, admin_id, f"מקור {tag}"), _board(client, admin_id, f"יעד {tag}")
    for bid in (a, b):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": who, "role": "editor"})
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in _cols(client, a) if x["type"] == "connect")
    return a, b, c


_ITEM_DOORS = ("", "/comments", "/files", "/activity", "/activity/export")


# ── the baseline, so the tests below are about revocation and not about setup ─

def test_while_they_have_access_they_can_see_and_open_it(client, admin_id, guinea_id):
    a, b, c = _setup(client, admin_id, guinea_id, "b1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "סוד")
    _set(client, src, c["id"], [x], admin_id)
    assert _cell(client, src, c["id"], guinea_id) == [x]
    assert client.get(f"/api/tasks/lookup?ids={x}", headers=AS(guinea_id)).json()["items"][0]["title"] == "סוד"
    for door in _ITEM_DOORS:
        assert client.get(f"/api/tasks/{x}{door}", headers=AS(guinea_id)).status_code == 200, door


# ── after it is taken away ──────────────────────────────────────────────────

def test_losing_board_membership_takes_the_link_with_it(client, admin_id, guinea_id):
    a, b, c = _setup(client, admin_id, guinea_id, "r1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "סוד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}/members/{guinea_id}?actor_id={admin_id}")
    assert _cell(client, src, c["id"], guinea_id) == []
    entry = client.get(f"/api/tasks/lookup?ids={x}", headers=AS(guinea_id)).json()["items"][0]
    assert entry.get("restricted") is True
    assert not entry.get("title") and not entry.get("board_name") and not entry.get("board_id")


def test_an_item_level_block_takes_the_link_with_it(client, admin_id, guinea_id):
    a, b, c = _setup(client, admin_id, guinea_id, "r2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "סוד")
    _set(client, src, c["id"], [x], admin_id)
    client.post(f"/api/tasks/{x}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"})
    assert _cell(client, src, c["id"], guinea_id) == []
    assert client.get(f"/api/tasks/{x}", headers=AS(guinea_id)).status_code == 403


def test_every_door_into_the_item_is_shut(client, admin_id, guinea_id):
    """An id was enough to read the conversation, the files and the whole
    history — title included — on a board the caller was never invited to.
    Seeing a link is not permission to open what it points at, and that has to
    hold on every entry point, not only on GET /api/tasks/{id}."""
    a, b, c = _setup(client, admin_id, guinea_id, "r3")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "סוד")
    _set(client, src, c["id"], [x], admin_id)
    client.post(f"/api/tasks/{x}/comments", json={"actor_id": admin_id, "content": "תוכן פנימי"})
    client.delete(f"/api/boards/{b}/members/{guinea_id}?actor_id={admin_id}")
    reachable = [door for door in _ITEM_DOORS
                 if client.get(f"/api/tasks/{x}{door}", headers=AS(guinea_id)).status_code not in (403, 404)]
    assert not reachable, f"still reachable without access: {reachable}"


def test_the_count_of_hidden_links_does_not_leak(client, admin_id, guinea_id):
    a, b, c = _setup(client, admin_id, guinea_id, "r4")
    cols = [dict(x, connect={**(x.get("connect") or {}), "board_ids": [a, b]})
            if x["id"] == c["id"] else x for x in _cols(client, a)]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    src, keep = _item(client, a, admin_id, "מקור"), _item(client, a, admin_id, "גלוי")
    hidden = [_item(client, b, admin_id, f"סוד {i}") for i in range(3)]
    _set(client, src, c["id"], [keep] + hidden, admin_id)
    client.delete(f"/api/boards/{b}/members/{guinea_id}?actor_id={admin_id}")
    assert _cell(client, src, c["id"], guinea_id) == [keep], "the hidden links are still counted"


# ── the history stores connect values as raw id lists ───────────────────────

def test_the_item_log_does_not_publish_hidden_ids(client, admin_id, guinea_id):
    """The log is a second way to read the ids the cell withholds, and worse, a
    way to notice hidden links exist at all."""
    a, b, c = _setup(client, admin_id, guinea_id, "l1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "סוד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}/members/{guinea_id}?actor_id={admin_id}")
    r = client.get(f"/api/tasks/{src}/activity", headers=AS(guinea_id))
    assert r.status_code == 200 and str(x) not in r.text


def test_the_board_log_does_not_publish_hidden_ids(client, admin_id, guinea_id):
    a, b, c = _setup(client, admin_id, guinea_id, "l2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "סוד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}/members/{guinea_id}?actor_id={admin_id}")
    r = client.get(f"/api/boards/{a}/activity", headers=AS(guinea_id))
    assert r.status_code == 200 and str(x) not in r.text


def test_the_csv_exports_do_not_publish_them_either(client, admin_id, guinea_id):
    a, b, c = _setup(client, admin_id, guinea_id, "l3")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "סוד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}/members/{guinea_id}?actor_id={admin_id}")
    for url in (f"/api/tasks/{src}/activity/export", f"/api/boards/{a}/activity/export"):
        r = client.get(url, headers=AS(guinea_id))
        assert r.status_code == 200 and str(x) not in r.text, url


def test_a_visible_link_still_shows_in_the_log(client, admin_id, guinea_id):
    """The redaction is a filter on ids, and getting that predicate wrong would
    silently empty the log of every connect change."""
    a, b, c = _setup(client, admin_id, guinea_id, "l4")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "גלוי")
    _set(client, src, c["id"], [x], admin_id)
    r = client.get(f"/api/tasks/{src}/activity", headers=AS(guinea_id))
    assert str(x) in r.text, "a link the viewer may see vanished from the log"


def test_the_owner_still_sees_the_whole_log(client, admin_id, guinea_id):
    a, b, c = _setup(client, admin_id, guinea_id, "l5")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "סוד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}/members/{guinea_id}?actor_id={admin_id}")
    r = client.get(f"/api/tasks/{src}/activity", headers=AS(admin_id))
    assert str(x) in r.text, "the redaction applied to someone who does have access"
