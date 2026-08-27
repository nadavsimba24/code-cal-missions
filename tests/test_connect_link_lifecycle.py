"""Removing a link, and the link rows outliving what they describe.

Removing a link severs the relationship and nothing else: neither item is
deleted and neither item's data changes. On a two-way column the removal has to
show on both sides, and the two sides must never end up disagreeing about
whether a relationship exists — including after the item, the board or the
column at one end is destroyed.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import ItemLink

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


def _setup(client, admin_id, tag):
    a, b = _board(client, admin_id, f"מקור {tag}"), _board(client, admin_id, f"יעד {tag}")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in _cols(client, a) if x["type"] == "connect")
    return a, b, c, c["connect"]["mirror"][str(b)]


def _link_rows(task_id):
    with Session(cityos_main.engine) as db:
        return db.query(ItemLink).filter(
            (ItemLink.a_task_id == task_id) | (ItemLink.b_task_id == task_id)).count()


# ── the two sides agree, whichever side acts ────────────────────────────────

def test_removing_from_the_source_clears_the_mirror(client, admin_id):
    a, b, c, mirror = _setup(client, admin_id, "t1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [], admin_id)
    assert _cell(client, src, c["id"], admin_id) == []
    assert _cell(client, x, mirror, admin_id) == []


def test_removing_from_the_mirror_clears_the_source(client, admin_id):
    a, b, c, mirror = _setup(client, admin_id, "t2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, x, mirror, [], admin_id)
    assert _cell(client, x, mirror, admin_id) == []
    assert _cell(client, src, c["id"], admin_id) == []


def test_the_two_sides_never_disagree(client, admin_id):
    a, b, c, mirror = _setup(client, admin_id, "t3")
    src = _item(client, a, admin_id, "מקור")
    xs = [_item(client, b, admin_id, f"יעד {i}") for i in range(3)]
    _set(client, src, c["id"], xs, admin_id)
    for x in xs:
        assert _cell(client, x, mirror, admin_id) == [src]
    _set(client, xs[1], mirror, [], admin_id)                       # one, from the far side
    assert sorted(_cell(client, src, c["id"], admin_id)) == sorted([xs[0], xs[2]])
    assert _cell(client, xs[1], mirror, admin_id) == []
    _set(client, src, c["id"], [], admin_id)                        # the rest, from this side
    for x in xs:
        assert _cell(client, x, mirror, admin_id) == [], f"{x} still points back"


# ── nothing but the reference is touched ────────────────────────────────────

def test_removing_a_link_deletes_neither_item(client, admin_id):
    a, b, c, mirror = _setup(client, admin_id, "t4")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _set(client, src, c["id"], [], admin_id)
    for tid, title in ((src, "מקור"), (x, "יעד")):
        r = client.get(f"/api/tasks/{tid}", headers=AS(admin_id))
        assert r.status_code == 200 and r.json()["title"] == title


def test_removing_a_link_changes_neither_item(client, admin_id):
    a, b, c, mirror = _setup(client, admin_id, "t5")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.patch(f"/api/tasks/{x}?user_id={admin_id}",
                 json={"description": "תיאור", "priority": "high"})
    _set(client, src, c["id"], [x], admin_id)
    keys = ("title", "description", "status", "priority", "due_date", "group_id", "assignees")
    snap = lambda t: {k: client.get(f"/api/tasks/{t}", headers=AS(admin_id)).json().get(k) for k in keys}
    before = (snap(src), snap(x))
    _set(client, src, c["id"], [], admin_id)
    assert (snap(src), snap(x)) == before


# ── the bin: hidden while binned, back on restore ───────────────────────────

def test_binning_an_item_marks_the_link_rather_than_dropping_it(client, admin_id):
    """The deletion policy here is a recycle bin, so the honest answer is "that
    item was deleted", not silence. Dropping it would give no hint that
    anything is pending and the link would reappear out of nowhere on restore."""
    a, b, c, mirror = _setup(client, admin_id, "t6")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/tasks/{x}?user_id={admin_id}")
    assert _cell(client, src, c["id"], admin_id) == [x], "the link was dropped instead of marked"
    entry = client.get(f"/api/tasks/lookup?ids={x}", headers=AS(admin_id)).json()["items"][0]
    assert entry["deleted"] is True and entry["title"] == "יעד"


def test_a_live_link_is_not_marked_deleted(client, admin_id):
    a, b, c, mirror = _setup(client, admin_id, "t6b")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    entry = client.get(f"/api/tasks/lookup?ids={x}", headers=AS(admin_id)).json()["items"][0]
    assert entry["deleted"] is False


def test_both_sides_show_the_deleted_mark(client, admin_id):
    """A two-way link is one row, so every reference to it updates together."""
    a, b, c, mirror = _setup(client, admin_id, "t6c")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/tasks/{src}?user_id={admin_id}")
    assert _cell(client, x, mirror, admin_id) == [src]
    entry = client.get(f"/api/tasks/lookup?ids={src}", headers=AS(admin_id)).json()["items"][0]
    assert entry["deleted"] is True


def test_a_binned_item_cannot_be_newly_linked(client, admin_id):
    """Keeping an existing link to a binned item is what makes restore work.
    Creating one is not — the picker never offers it, and neither does the API."""
    a, b, c, mirror = _setup(client, admin_id, "t6d")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.delete(f"/api/tasks/{x}?user_id={admin_id}")
    _set(client, src, c["id"], [x], admin_id)
    assert _cell(client, src, c["id"], admin_id) == []


def test_a_binned_item_is_not_offered_by_the_picker(client, admin_id):
    a, b, c, mirror = _setup(client, admin_id, "t6e")
    x = _item(client, b, admin_id, "יעד")
    client.delete(f"/api/tasks/{x}?user_id={admin_id}")
    found = client.get(f"/api/items/search?board_ids={b}", headers=AS(admin_id)).json()
    assert x not in [i["id"] for i in found["items"]]


def test_editing_the_cell_keeps_a_binned_link(client, admin_id):
    """Otherwise touching the cell while an item sits in the bin would destroy
    the relationship that restore is supposed to bring back."""
    a, b, c, mirror = _setup(client, admin_id, "t6f")
    src = _item(client, a, admin_id, "מקור")
    x, y = _item(client, b, admin_id, "בסל"), _item(client, b, admin_id, "חי")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/tasks/{x}?user_id={admin_id}")
    _set(client, src, c["id"], [x, y], admin_id)          # the client sends back what it was shown
    client.post(f"/api/tasks/{x}/restore", json={"actor_id": admin_id})
    assert sorted(_cell(client, src, c["id"], admin_id)) == sorted([x, y])


def test_restoring_it_brings_the_link_back(client, admin_id):
    """Which is why the bin must not destroy the row — only purging does."""
    a, b, c, mirror = _setup(client, admin_id, "t7")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/tasks/{x}?user_id={admin_id}")
    client.post(f"/api/tasks/{x}/restore", json={"actor_id": admin_id})
    assert _cell(client, src, c["id"], admin_id) == [x]
    assert _cell(client, x, mirror, admin_id) == [src]


# ── rows must not outlive what they describe ────────────────────────────────

def test_purging_an_item_takes_its_link_rows(client, admin_id):
    """Nothing cascades a link row away: it belongs to neither side, which is
    the point of storing one row instead of two."""
    a, b, c, mirror = _setup(client, admin_id, "t8")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    assert _link_rows(x) == 1
    client.delete(f"/api/tasks/{x}?user_id={admin_id}")
    client.delete(f"/api/boards/{b}/trash/{x}?actor_id={admin_id}")
    assert _link_rows(x) == 0, "a row is left describing a relationship to a destroyed item"
    assert _cell(client, src, c["id"], admin_id) == []


def test_purging_a_board_takes_the_links_off_the_surviving_board(client, admin_id):
    """Links reach across boards, so the far end is on a board that lives on."""
    a, b, c, mirror = _setup(client, admin_id, "t9")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    client.delete(f"/api/trash/boards/{b}?user_id={admin_id}")
    assert _link_rows(src) == 0, "the destroyed board left its links on the surviving one"
    assert _cell(client, src, c["id"], admin_id) == []


def test_deleting_the_column_takes_its_links(client, admin_id):
    """The rows are keyed by (item, column). Left behind, the mirror on the
    other board still finds them and the two sides disagree about whether the
    relationship exists at all."""
    a, b, c, mirror = _setup(client, admin_id, "t10")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    remaining = [col for col in _cols(client, a) if col["id"] != c["id"]]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": remaining})
    assert _link_rows(src) == 0
    assert _cell(client, x, mirror, admin_id) == [], "the far side still shows a link with no column behind it"


def test_deleting_an_unrelated_column_leaves_the_links_alone(client, admin_id):
    a, b, c, mirror = _setup(client, admin_id, "t11")
    cols = _cols(client, a) + [{"type": "text", "title": "הערה"}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    note = next(x for x in _cols(client, a) if x["type"] == "text" and x["title"] == "הערה")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    remaining = [col for col in _cols(client, a) if col["id"] != note["id"]]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": remaining})
    assert _cell(client, src, c["id"], admin_id) == [x], "an unrelated column removal took the links with it"
    assert _cell(client, x, mirror, admin_id) == [src]


def test_a_one_way_column_marks_and_restores_too(client, admin_id):
    """A one-way link lives in the cell rather than in item_links, so it takes
    a different route to the same two answers."""
    a, b = _board(client, admin_id, "מקור t12"), _board(client, admin_id, "יעד t12")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": False}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in _cols(client, a) if x["type"] == "connect")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/tasks/{x}?user_id={admin_id}")
    assert _cell(client, src, c["id"], admin_id) == [x]
    assert client.get(f"/api/tasks/lookup?ids={x}", headers=AS(admin_id)).json()["items"][0]["deleted"] is True
    client.post(f"/api/tasks/{x}/restore", json={"actor_id": admin_id})
    entry = client.get(f"/api/tasks/lookup?ids={x}", headers=AS(admin_id)).json()["items"][0]
    assert entry["deleted"] is False and entry["title"] == "יעד"


def test_purging_leaves_no_mark_because_there_is_nothing_to_restore(client, admin_id):
    a, b, c, mirror = _setup(client, admin_id, "t13")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/tasks/{x}?user_id={admin_id}")
    client.delete(f"/api/boards/{b}/trash/{x}?actor_id={admin_id}")
    assert _cell(client, src, c["id"], admin_id) == [], "an active link to a destroyed item"
    assert _link_rows(x) == 0


def test_deleting_the_column_does_not_delete_the_items(client, admin_id):
    """The links go; the things they pointed at stay, on both boards."""
    a, b, c, mirror = _setup(client, admin_id, "t14")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    remaining = [col for col in _cols(client, a) if col["id"] != c["id"]]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": remaining})
    for tid, title in ((src, "מקור"), (x, "יעד")):
        r = client.get(f"/api/tasks/{tid}", headers=AS(admin_id))
        assert r.status_code == 200 and r.json()["title"] == title


def test_the_impact_endpoint_reports_what_deletion_would_cost(client, admin_id):
    """What the confirmation dialog is built from. Counted on the server: the
    cell a client holds has already been filtered to what its viewer may see,
    so counting there would understate it for the person about to delete."""
    a, b, c, mirror = _setup(client, admin_id, "t15")
    srcs = [_item(client, a, admin_id, f"מקור {i}") for i in range(2)]
    xs = [_item(client, b, admin_id, f"יעד {i}") for i in range(3)]
    _set(client, srcs[0], c["id"], xs[:2], admin_id)
    _set(client, srcs[1], c["id"], xs[2:], admin_id)
    imp = client.get(f"/api/boards/{a}/columns/{c['id']}/impact", headers=AS(admin_id)).json()
    assert imp["two_way"] is True
    assert imp["links"] == 3 and imp["items"] == 2
    assert imp["mirrors"] and imp["mirrors"][0]["board_id"] == b
    assert imp["mirrors"][0]["col_id"] == mirror
    assert imp["mirrors"][0]["board_name"] == f"יעד t15"


def test_the_impact_endpoint_counts_a_one_way_column_too(client, admin_id):
    a, b = _board(client, admin_id, "מקור t16"), _board(client, admin_id, "יעד t16")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": False}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in _cols(client, a) if x["type"] == "connect")
    src = _item(client, a, admin_id, "מקור")
    xs = [_item(client, b, admin_id, f"יעד {i}") for i in range(2)]
    _set(client, src, c["id"], xs, admin_id)
    imp = client.get(f"/api/boards/{a}/columns/{c['id']}/impact", headers=AS(admin_id)).json()
    assert imp["two_way"] is False and imp["links"] == 2 and imp["items"] == 1
    assert imp["mirrors"] == []


def test_only_a_board_admin_may_ask_what_deletion_would_cost(client, admin_id, guinea_id):
    a, b, c, mirror = _setup(client, admin_id, "t17")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    r = client.get(f"/api/boards/{a}/columns/{c['id']}/impact", headers=AS(guinea_id))
    assert r.status_code == 403
