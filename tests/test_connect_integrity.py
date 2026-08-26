"""Links are identity, not text — and the limits and loading around that.

A link is a row pointing at an item id, so nothing anyone types can break it.
The rest is what has to be true for that to stay safe at scale.
"""
from sqlalchemy import event
import main as cityos_main

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


def _setup(client, admin_id, tag, two_way=True):
    a, b = _board(client, admin_id, f"מקור {tag}"), _board(client, admin_id, f"יעד {tag}")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    return a, b, next(x for x in _cols(client, a) if x["type"] == "connect")


class _Queries:
    """Counts SQL statements issued inside the block."""
    def __enter__(self):
        self.n = 0
        self._h = lambda *a, **k: setattr(self, "n", self.n + 1)
        event.listen(cityos_main.engine, "before_cursor_execute", self._h)
        return self

    def __exit__(self, *exc):
        event.remove(cityos_main.engine, "before_cursor_execute", self._h)
        return False


# ── the link is the id ──────────────────────────────────────────────────────

def test_renaming_the_linked_item_does_not_touch_the_link(client, admin_id):
    a, b, c = _setup(client, admin_id, "n1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "שם ישן")
    _set(client, src, c["id"], [x], admin_id)
    client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"title": "שם אחר לגמרי"})
    assert _cell(client, src, c["id"], admin_id) == [x]
    entry = client.get(f"/api/tasks/lookup?ids={x}", headers=AS(admin_id)).json()["items"][0]
    assert entry["title"] == "שם אחר לגמרי", "the link still shows the old name"


def test_renaming_the_board_does_not_touch_the_links(client, admin_id):
    a, b, c = _setup(client, admin_id, "n2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.patch(f"/api/boards/{b}", json={"actor_id": admin_id, "name": "שם לוח חדש"})
    assert _cell(client, src, c["id"], admin_id) == [x]
    assert client.get(f"/api/tasks/lookup?ids={x}",
                      headers=AS(admin_id)).json()["items"][0]["board_name"] == "שם לוח חדש"


def test_an_item_that_does_not_exist_cannot_be_linked(client, admin_id):
    a, b, c = _setup(client, admin_id, "n3")
    src = _item(client, a, admin_id, "מקור")
    _set(client, src, c["id"], [999999], admin_id)
    assert _cell(client, src, c["id"], admin_id) == []


# ── one link per pair, per cell ─────────────────────────────────────────────

def test_the_same_item_twice_in_one_cell_is_one_link(client, admin_id):
    a, b, c = _setup(client, admin_id, "d1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x, x, x], admin_id)
    assert _cell(client, src, c["id"], admin_id) == [x]


def test_the_same_holds_for_a_one_way_column(client, admin_id):
    """A one-way cell is a plain list, so nothing deduplicated it — the same
    item three times stayed in the cell three times."""
    a, b, c = _setup(client, admin_id, "d2", two_way=False)
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x, x, x], admin_id)
    assert _cell(client, src, c["id"], admin_id) == [x]


def test_relinking_an_item_already_there_changes_nothing(client, admin_id):
    a, b, c = _setup(client, admin_id, "d3")
    src = _item(client, a, admin_id, "מקור")
    x, y = _item(client, b, admin_id, "א"), _item(client, b, admin_id, "ב")
    _set(client, src, c["id"], [x, y], admin_id)
    _set(client, src, c["id"], [x, y, x], admin_id)
    assert _cell(client, src, c["id"], admin_id) == [x, y]


# ── system limits ───────────────────────────────────────────────────────────

def test_a_board_has_a_connect_column_budget(client, admin_id):
    a, b = _board(client, admin_id, "מקור l1"), _board(client, admin_id, "יעד l1")
    over = cityos_main._max_connect_cols() + 1
    cols = _cols(client, a) + [{"type": "connect", "title": f"קישור {i}",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": False}}
                               for i in range(over)]
    r = client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    assert r.status_code == 400
    assert len([x for x in _cols(client, a) if x["type"] == "connect"]) == 0, "some were saved anyway"


def test_the_budget_still_allows_the_limit_itself(client, admin_id):
    a, b = _board(client, admin_id, "מקור l2"), _board(client, admin_id, "יעד l2")
    n = cityos_main._max_connect_cols()
    cols = _cols(client, a) + [{"type": "connect", "title": f"קישור {i}",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": False}}
                               for i in range(n)]
    assert client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols}).status_code == 200
    assert len([x for x in _cols(client, a) if x["type"] == "connect"]) == n


def test_a_cell_has_a_link_budget(client, admin_id):
    a, b, c = _setup(client, admin_id, "l3", two_way=False)
    cap = cityos_main._max_links_per_cell()
    src = _item(client, a, admin_id, "מקור")
    ids = [_item(client, b, admin_id, f"יעד {i}") for i in range(cap + 5)]
    _set(client, src, c["id"], ids, admin_id)
    got = _cell(client, src, c["id"], admin_id)
    assert len(got) == cap and got == ids[:cap], "the cap did not keep the first ones in order"


# ── loading ─────────────────────────────────────────────────────────────────

def test_the_board_payload_carries_ids_not_the_linked_items_data(client, admin_id):
    """Opening a board must not drag in the contents of every board it links
    to. The cells hold ids; the names are fetched for what is on screen."""
    a, b, c = _setup(client, admin_id, "p1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "כותרת רחוקה מאוד")
    _set(client, src, c["id"], [x], admin_id)
    body = client.get(f"/api/boards/{a}", headers=AS(admin_id)).text
    assert "כותרת רחוקה מאוד" not in body
    assert "יעד p1" not in body, "the linked board's name came along too"


def test_loading_cost_does_not_grow_with_the_number_of_links(client, admin_id):
    """Serializing an item used to ask for its links and then ask whether each
    was visible — two round trips per item, so a board paid for a table showing
    a handful of names. Both are batched for the whole board now, and this is
    the invariant that says so: four times the links, the same number of
    queries."""
    a, b, c = _setup(client, admin_id, "p2")
    far = [_item(client, b, admin_id, f"רחוק {i}") for i in range(8)]
    near = [_item(client, a, admin_id, f"קרוב {i}") for i in range(12)]
    for t in near:
        _set(client, t, c["id"], far[:1], admin_id)
    with _Queries() as q1:
        client.get(f"/api/boards/{a}", headers=AS(admin_id))
    for t in near:
        _set(client, t, c["id"], far[:4], admin_id)
    with _Queries() as q4:
        client.get(f"/api/boards/{a}", headers=AS(admin_id))
    assert q4.n <= q1.n + 2, f"{q1.n} queries for 12 links, {q4.n} for 48 — it scales with the links"


def test_a_write_does_not_read_a_stale_link_cache(client, admin_id):
    """The batch is a read-path cache; keeping it across a write would answer
    from before the write."""
    a, b, c = _setup(client, admin_id, "p3")
    src = _item(client, a, admin_id, "מקור")
    x, y = _item(client, b, admin_id, "א"), _item(client, b, admin_id, "ב")
    _set(client, src, c["id"], [x], admin_id)
    client.get(f"/api/boards/{a}", headers=AS(admin_id))
    _set(client, src, c["id"], [x, y], admin_id)
    assert _cell(client, src, c["id"], admin_id) == [x, y]
