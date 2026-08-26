"""Mirror fields (שדה מראה): showing a field of the linked item, not a copy of it.

The value is computed on every read through the connect column, so it follows
the source with nothing stored, nothing to keep in step and nothing to migrate.
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


def _texts(client, tid, col_id, uid):
    return [c["text"] for c in _cell(client, tid, col_id, uid)]


def _set(client, tid, col_id, ids, uid):
    return client.patch(f"/api/tasks/{tid}?user_id={uid}",
                        json={"custom_fields": {col_id: ids}}, headers=AS(uid))


def _setup(client, admin_id, tag, field, two_way=True, extra=None):
    """Board a linked to board b, with a mirror column showing `field`."""
    a, b = _board(client, admin_id, f"מקור {tag}"), _board(client, admin_id, f"יעד {tag}")
    if extra:
        client.patch(f"/api/boards/{b}", json={"actor_id": admin_id,
                                               "columns": _cols(client, b) + extra})
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    conn = next(x for x in _cols(client, a) if x["type"] == "connect")
    cols = _cols(client, a) + [{"type": "mirror", "title": "מראה",
                                "mirror_of": {"connect": conn["id"], "field": field}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    mir = next(x for x in _cols(client, a) if x["type"] == "mirror")
    return a, b, conn, mir


# ── it shows the linked item's field ────────────────────────────────────────

def test_it_shows_the_linked_items_title(client, admin_id):
    a, b, conn, mir = _setup(client, admin_id, "m1", "title")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "היעד שלי")
    _set(client, src, conn["id"], [x], admin_id)
    assert _texts(client, src, mir["id"], admin_id) == ["היעד שלי"]


def test_it_shows_status_with_its_colour(client, admin_id):
    a, b, conn, mir = _setup(client, admin_id, "m2", "status")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"status": "in_progress"})
    _set(client, src, conn["id"], [x], admin_id)
    cell = _cell(client, src, mir["id"], admin_id)
    assert len(cell) == 1 and cell[0]["color"], "a status arrived without its colour"


def test_it_follows_a_change_at_the_source(client, admin_id):
    """The point of the feature: no copy to keep in step."""
    a, b, conn, mir = _setup(client, admin_id, "m3", "title")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "לפני")
    _set(client, src, conn["id"], [x], admin_id)
    assert _texts(client, src, mir["id"], admin_id) == ["לפני"]
    client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"title": "אחרי"})
    assert _texts(client, src, mir["id"], admin_id) == ["אחרי"]


def test_it_mirrors_a_custom_column_on_the_linked_board(client, admin_id):
    a, b, conn, mir = _setup(client, admin_id, "m4", "__later__",
                             extra=[{"type": "text", "title": "מספר ספק"}])
    sup = next(c for c in _cols(client, b) if c["title"] == "מספר ספק")
    cols = [dict(c, mirror_of={"connect": conn["id"], "field": sup["id"]})
            if c["id"] == mir["id"] else c for c in _cols(client, a)]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"custom_fields": {sup["id"]: "SUP-4471"}})
    _set(client, src, conn["id"], [x], admin_id)
    assert _texts(client, src, mir["id"], admin_id) == ["SUP-4471"]


def test_several_links_give_several_values(client, admin_id):
    a, b, conn, mir = _setup(client, admin_id, "m5", "title")
    src = _item(client, a, admin_id, "מקור")
    xs = [_item(client, b, admin_id, f"יעד {i}") for i in range(3)]
    _set(client, src, conn["id"], xs, admin_id)
    assert _texts(client, src, mir["id"], admin_id) == ["יעד 0", "יעד 1", "יעד 2"]


def test_no_links_means_an_empty_cell(client, admin_id):
    a, b, conn, mir = _setup(client, admin_id, "m6", "title")
    src = _item(client, a, admin_id, "מקור")
    assert _cell(client, src, mir["id"], admin_id) == []


def test_a_one_way_connect_column_works_the_same(client, admin_id):
    a, b, conn, mir = _setup(client, admin_id, "m7", "title", two_way=False)
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, conn["id"], [x], admin_id)
    assert _texts(client, src, mir["id"], admin_id) == ["יעד"]


# ── it holds no data of its own ─────────────────────────────────────────────

def test_it_cannot_be_written_to(client, admin_id):
    """Accepting a write would store a value the next read discards — the cell
    would appear to change and snap back."""
    a, b, conn, mir = _setup(client, admin_id, "w1", "title")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "אמת")
    _set(client, src, conn["id"], [x], admin_id)
    client.patch(f"/api/tasks/{src}?user_id={admin_id}",
                 json={"custom_fields": {mir["id"]: [{"text": "שקר"}]}})
    assert _texts(client, src, mir["id"], admin_id) == ["אמת"]


def test_creating_an_item_cannot_seed_one(client, admin_id):
    a, b, conn, mir = _setup(client, admin_id, "w2", "title")
    nt = client.post("/api/tasks", json={"board_id": a, "title": "חדש", "user_id": admin_id,
                                         "custom_fields": {mir["id"]: [{"text": "שקר"}]}}).json()
    assert _cell(client, nt["id"], mir["id"], admin_id) == []


def test_removing_the_link_empties_it(client, admin_id):
    a, b, conn, mir = _setup(client, admin_id, "w3", "title")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, conn["id"], [x], admin_id)
    _set(client, src, conn["id"], [], admin_id)
    assert _cell(client, src, mir["id"], admin_id) == []


def test_deleting_the_connect_column_leaves_it_empty_not_broken(client, admin_id):
    a, b, conn, mir = _setup(client, admin_id, "w4", "title")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, conn["id"], [x], admin_id)
    remaining = [c for c in _cols(client, a) if c["id"] != conn["id"]]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": remaining})
    r = client.get(f"/api/tasks/{src}", headers=AS(admin_id))
    assert r.status_code == 200
    assert (r.json().get("custom_fields") or {}).get(mir["id"]) == []


# ── it must not become a way around the link's own permissions ──────────────

def test_it_shows_nothing_for_a_link_you_may_not_see(client, admin_id, guinea_id):
    """The connect column withholds those ids; a mirror reading through it must
    not hand back the field they point at."""
    a, b, conn, mir = _setup(client, admin_id, "p1", "title")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "סוד")
    _set(client, src, conn["id"], [x], admin_id)
    assert _texts(client, src, mir["id"], admin_id) == ["סוד"]
    assert _cell(client, src, mir["id"], guinea_id) == [], "the mirror leaked a hidden item's field"


def test_only_the_visible_links_contribute(client, admin_id, guinea_id):
    a, b, conn, mir = _setup(client, admin_id, "p2", "title")
    cols = [dict(c, connect={**(c.get("connect") or {}), "board_ids": [a, b]})
            if c["id"] == conn["id"] else c for c in _cols(client, a)]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    src = _item(client, a, admin_id, "מקור")
    seen, hidden = _item(client, a, admin_id, "גלוי"), _item(client, b, admin_id, "סוד")
    _set(client, src, conn["id"], [seen, hidden], admin_id)
    assert _texts(client, src, mir["id"], guinea_id) == ["גלוי"]


# ── what a mirror may be pointed at ─────────────────────────────────────────

def test_the_sources_endpoint_offers_the_targets_fields(client, admin_id):
    a, b, conn, mir = _setup(client, admin_id, "s1", "title",
                             extra=[{"type": "text", "title": "מספר ספק"}])
    src = client.get(f"/api/boards/{a}/mirror-sources", headers=AS(admin_id)).json()["sources"]
    entry = next(s for s in src if s["connect_id"] == conn["id"])
    labels = [f["label"] for f in entry["fields"]]
    assert "סטטוס" in labels and "תאריך יעד" in labels
    assert "מספר ספק" in labels, "a custom column on the target board was not offered"
    assert entry["target_boards"] == [b]


def test_the_sources_endpoint_does_not_offer_links_or_other_mirrors(client, admin_id):
    """A mirror of a link, or of another mirror, is its own feature."""
    a, b, conn, mir = _setup(client, admin_id, "s2", "title")
    entry = next(s for s in client.get(f"/api/boards/{a}/mirror-sources",
                                       headers=AS(admin_id)).json()["sources"]
                 if s["connect_id"] == conn["id"])
    assert all(f.get("type") not in ("connect", "mirror") for f in entry["fields"])
