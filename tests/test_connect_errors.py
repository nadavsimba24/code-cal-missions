"""What the system says when a link does not take.

Every one of these was already refused — correctly — and refused in silence.
The user picked an item, saved, and it simply was not there. Which of the five
things went wrong is the part that was missing.
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


def _set(client, tid, col_id, ids, uid, **extra):
    return client.patch(f"/api/tasks/{tid}?user_id={uid}",
                        json={"custom_fields": {col_id: ids}, **extra}, headers=AS(uid))


def _setup(client, admin_id, tag, two_way=True):
    a, b = _board(client, admin_id, f"מקור {tag}"), _board(client, admin_id, f"יעד {tag}")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    return a, b, next(x for x in _cols(client, a) if x["type"] == "connect")


def _reasons(r):
    return {w["reason"] for w in (r.json().get("link_warnings") or [])}


# ── the five ────────────────────────────────────────────────────────────────

def test_the_target_was_deleted_during_the_operation(client, admin_id):
    a, b, c = _setup(client, admin_id, "e1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.delete(f"/api/tasks/{x}?user_id={admin_id}")          # binned while the picker was open
    r = _set(client, src, c["id"], [x], admin_id)
    assert "deleted" in _reasons(r)
    assert "נמחק" in r.json()["link_message"]
    assert _cell(client, src, c["id"], admin_id) == []


def test_the_target_no_longer_exists_at_all(client, admin_id):
    a, b, c = _setup(client, admin_id, "e2")
    src = _item(client, a, admin_id, "מקור")
    r = _set(client, src, c["id"], [999999], admin_id)
    assert "missing" in _reasons(r)


def test_the_user_no_longer_has_permission_to_the_chosen_item(client, admin_id, guinea_id):
    a, b, c = _setup(client, admin_id, "e3")
    for bid in (a, b):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.delete(f"/api/boards/{b}/members/{guinea_id}?actor_id={admin_id}")
    r = _set(client, src, c["id"], [x], guinea_id)
    assert "forbidden" in _reasons(r)
    assert "הרשאת" in r.json()["link_message"]


def test_the_target_board_is_unavailable(client, admin_id):
    a, b, c = _setup(client, admin_id, "e4")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    r = _set(client, src, c["id"], [x], admin_id)
    assert "board_unavailable" in _reasons(r)
    assert "סל המחזור" in r.json()["link_message"]


def test_the_reverse_has_nowhere_to_appear(client, admin_id):
    """A two-way link with no column on the far board to show it is not a
    relationship that can be stored."""
    a, b = _board(client, admin_id, "מקור e5"), _board(client, admin_id, "יעד e5")
    other = _board(client, admin_id, "שלישי e5")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in _cols(client, a) if x["type"] == "connect")
    src, stray = _item(client, a, admin_id, "מקור"), _item(client, other, admin_id, "זר")
    r = _set(client, src, c["id"], [stray], admin_id)
    assert "no_mirror" in _reasons(r)


def test_going_over_the_cell_limit_says_so(client, admin_id):
    a, b, c = _setup(client, admin_id, "e6", two_way=False)
    cap = cityos_main._max_links_per_cell()
    src = _item(client, a, admin_id, "מקור")
    ids = [_item(client, b, admin_id, f"יעד {i}") for i in range(cap + 2)]
    r = _set(client, src, c["id"], ids, admin_id)
    assert "limit" in _reasons(r)
    assert len(_cell(client, src, c["id"], admin_id)) == cap


# ── a save that worked says nothing ─────────────────────────────────────────

def test_a_link_that_takes_produces_no_warning(client, admin_id):
    a, b, c = _setup(client, admin_id, "ok1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    r = _set(client, src, c["id"], [x], admin_id)
    assert not r.json().get("link_warnings") and not r.json().get("link_message")


def test_the_good_ones_still_save_when_one_is_bad(client, admin_id):
    """One refused link must not cost the others."""
    a, b, c = _setup(client, admin_id, "ok2")
    src = _item(client, a, admin_id, "מקור")
    good1, good2 = _item(client, b, admin_id, "טוב 1"), _item(client, b, admin_id, "טוב 2")
    r = _set(client, src, c["id"], [good1, 999999, good2], admin_id)
    assert "missing" in _reasons(r)
    assert _cell(client, src, c["id"], admin_id) == [good1, good2]


# ── concurrent edits ────────────────────────────────────────────────────────

def test_a_concurrent_edit_of_the_same_cell_is_refused_not_overwritten(client, admin_id, member_id):
    """The client sends the whole desired list, so without this the second save
    silently erases the first."""
    a, b, c = _setup(client, admin_id, "x1")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    client.post(f"/api/boards/{b}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    src = _item(client, a, admin_id, "מקור")
    x, y = _item(client, b, admin_id, "של הראשון"), _item(client, b, admin_id, "של השני")
    # both open the picker against an empty cell
    _set(client, src, c["id"], [x], admin_id)                       # the first saves
    r = _set(client, src, c["id"], [y], member_id,
             expect={c["id"]: []})                                  # the second, stale
    assert r.status_code == 409
    assert _cell(client, src, c["id"], admin_id) == [x], "the stale save went through anyway"


def test_the_conflict_hands_back_what_is_there_now(client, admin_id):
    a, b, c = _setup(client, admin_id, "x2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    r = client.patch(f"/api/tasks/{src}?user_id={admin_id}",
                     json={"custom_fields": {c["id"]: []}, "expect": {c["id"]: []}})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["column"] == c["id"] and d["current"] == [x] and d["message"]


def test_a_save_that_matches_what_the_client_saw_goes_through(client, admin_id):
    a, b, c = _setup(client, admin_id, "x3")
    src = _item(client, a, admin_id, "מקור")
    x, y = _item(client, b, admin_id, "א"), _item(client, b, admin_id, "ב")
    _set(client, src, c["id"], [x], admin_id)
    r = client.patch(f"/api/tasks/{src}?user_id={admin_id}",
                     json={"custom_fields": {c["id"]: [x, y]}, "expect": {c["id"]: [x]}})
    assert r.status_code == 200
    assert _cell(client, src, c["id"], admin_id) == [x, y]


def test_expect_is_measured_against_what_that_reader_can_see(client, admin_id, guinea_id):
    """A hidden link must not make every save look like a conflict."""
    a = _board(client, admin_id, "מקור x4")
    seen_b, closed_b = _board(client, admin_id, "גלוי x4"), _board(client, admin_id, "סגור x4")
    for bid in (a, seen_b):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [seen_b, closed_b],
                                            "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in _cols(client, a) if x["type"] == "connect")
    src = _item(client, a, admin_id, "מקור")
    ok, secret = _item(client, seen_b, admin_id, "גלוי"), _item(client, closed_b, admin_id, "סוד")
    _set(client, src, c["id"], [ok, secret], admin_id)
    r = client.patch(f"/api/tasks/{src}?user_id={guinea_id}",
                     json={"custom_fields": {c["id"]: [ok]}, "expect": {c["id"]: [ok]}},
                     headers=AS(guinea_id))
    assert r.status_code == 200, "the hidden link made an honest save look like a conflict"


# ── the two-way guarantee ───────────────────────────────────────────────────

def test_a_failed_save_leaves_neither_side_changed(client, admin_id):
    """One shared row is what makes this true by construction: there is no
    state in which one side was written and the other was not."""
    a, b, c = _setup(client, admin_id, "t1")
    mirror = c["connect"]["mirror"][str(b)]
    src = _item(client, a, admin_id, "מקור")
    x, bad = _item(client, b, admin_id, "טוב"), 999999
    _set(client, src, c["id"], [x], admin_id)
    r = client.patch(f"/api/tasks/{src}?user_id={admin_id}",
                     json={"custom_fields": {c["id"]: [x, bad]}, "expect": {c["id"]: [999]}})
    assert r.status_code == 409
    assert _cell(client, src, c["id"], admin_id) == [x]
    assert _cell(client, x, mirror, admin_id) == [src], "the far side moved while this one did not"
    with Session(cityos_main.engine) as db:
        assert db.query(ItemLink).filter(
            (ItemLink.a_task_id == src) | (ItemLink.b_task_id == src)).count() == 1


def test_the_two_sides_are_one_row_so_they_cannot_disagree(client, admin_id):
    a, b, c = _setup(client, admin_id, "t2")
    mirror = c["connect"]["mirror"][str(b)]
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    with Session(cityos_main.engine) as db:
        rows = db.query(ItemLink).filter(
            (ItemLink.a_task_id == src) | (ItemLink.b_task_id == src)).all()
    assert len(rows) == 1, "two rows means two sides that can drift apart"
    assert _cell(client, src, c["id"], admin_id) == [x]
    assert _cell(client, x, mirror, admin_id) == [src]
