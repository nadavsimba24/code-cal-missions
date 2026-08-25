"""A two-way connect column: one relationship, visible from both boards."""
from sqlalchemy.orm import Session
import main as cityos_main
from models import ItemLink


def _mk_board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _mk_item(client, bid, admin_id, title):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _cell(client, bid, tid, col):
    t = next(x for x in client.get(f"/api/boards/{bid}").json()["tasks"] if x["id"] == tid)
    return (t.get("custom_fields") or {}).get(col) or []


def _setup(client, admin_id, tag):
    a = _mk_board(client, admin_id, f"מקור {tag}")
    b = _mk_board(client, admin_id, f"יעד {tag}")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    src = next(c for c in _cols(client, a) if c["type"] == "connect")
    return a, b, src


def test_configuring_it_creates_the_mirror_column_and_says_where(client, admin_id):
    a, b, src = _setup(client, admin_id, "1")
    mirror_id = (src["connect"].get("mirror") or {}).get(str(b))
    assert mirror_id, "the column does not record where the reverse link shows"
    mirror = next((c for c in _cols(client, b) if c["id"] == mirror_id), None)
    assert mirror is not None, "no counterpart column was created on the target board"
    assert mirror["type"] == "connect" and mirror["connect"]["two_way"] is True
    assert mirror["connect"]["mirror"][str(a)] == src["id"], "the counterpart does not point back"


def test_a_link_made_on_one_side_shows_on_the_other(client, admin_id):
    a, b, src = _setup(client, admin_id, "2")
    mirror_id = src["connect"]["mirror"][str(b)]
    ta, tb = _mk_item(client, a, admin_id, "פריט א"), _mk_item(client, b, admin_id, "פריט ב")
    client.patch(f"/api/tasks/{ta}?user_id={admin_id}",
                 json={"custom_fields": {src["id"]: [tb]}})
    assert _cell(client, a, ta, src["id"]) == [tb]
    assert _cell(client, b, tb, mirror_id) == [ta], "the reverse link is not visible on the target board"


def test_removing_from_one_side_removes_it_from_both(client, admin_id):
    a, b, src = _setup(client, admin_id, "3")
    mirror_id = src["connect"]["mirror"][str(b)]
    ta, tb = _mk_item(client, a, admin_id, "א"), _mk_item(client, b, admin_id, "ב")
    client.patch(f"/api/tasks/{ta}?user_id={admin_id}", json={"custom_fields": {src["id"]: [tb]}})
    # remove from the TARGET side
    client.patch(f"/api/tasks/{tb}?user_id={admin_id}", json={"custom_fields": {mirror_id: []}})
    assert _cell(client, b, tb, mirror_id) == []
    assert _cell(client, a, ta, src["id"]) == [], "removing on one side left the other side linked"


def test_it_is_one_row_not_two(client, admin_id):
    """The point of the design: a single logical relationship."""
    a, b, src = _setup(client, admin_id, "4")
    ta, tb = _mk_item(client, a, admin_id, "א"), _mk_item(client, b, admin_id, "ב")
    client.patch(f"/api/tasks/{ta}?user_id={admin_id}", json={"custom_fields": {src["id"]: [tb]}})
    with Session(cityos_main.engine) as db:
        rows = db.query(ItemLink).filter(ItemLink.a_task_id.in_([ta, tb])
                                         | ItemLink.b_task_id.in_([ta, tb])).all()
    assert len(rows) == 1, f"expected one relationship row, found {len(rows)}"


def test_linking_from_the_target_side_works_the_same(client, admin_id):
    a, b, src = _setup(client, admin_id, "5")
    mirror_id = src["connect"]["mirror"][str(b)]
    ta, tb = _mk_item(client, a, admin_id, "א"), _mk_item(client, b, admin_id, "ב")
    client.patch(f"/api/tasks/{tb}?user_id={admin_id}", json={"custom_fields": {mirror_id: [ta]}})
    assert _cell(client, a, ta, src["id"]) == [tb], "a link made on the target side did not appear on the source"


def test_a_one_way_column_is_untouched(client, admin_id):
    """The existing behaviour has to keep working exactly as before."""
    a = _mk_board(client, admin_id, "מקור חד")
    b = _mk_board(client, admin_id, "יעד חד")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור חד",
                                "connect": {"board_ids": [b], "multiple": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    src = next(c for c in _cols(client, a) if c["type"] == "connect")
    assert not (src["connect"] or {}).get("two_way")
    assert not any(c["type"] == "connect" for c in _cols(client, b)), \
        "a one-way column created a column on the target board"
    ta, tb = _mk_item(client, a, admin_id, "א"), _mk_item(client, b, admin_id, "ב")
    client.patch(f"/api/tasks/{ta}?user_id={admin_id}", json={"custom_fields": {src["id"]: [tb]}})
    assert _cell(client, a, ta, src["id"]) == [tb]


def test_reconfiguring_reuses_the_counterpart_instead_of_adding_another(client, admin_id):
    a, b, src = _setup(client, admin_id, "6")
    before = [c["id"] for c in _cols(client, b) if c["type"] == "connect"]
    cols = [c if c["id"] != src["id"] else {**c, "title": "קישור ששמו שונה"} for c in _cols(client, a)]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    after = [c["id"] for c in _cols(client, b) if c["type"] == "connect"]
    assert after == before, "saving again added a second counterpart column"


# ── the picker's data source ──────────────────────────────────────────
def test_the_picker_returns_a_page_not_the_whole_board(client, admin_id):
    """A board with thousands of items must not have to load all of them."""
    b = _mk_board(client, admin_id, "לוח גדול")
    # a new board is not necessarily empty, so count what is there first
    base = client.get(f"/api/items/search?board_ids={b}&limit=1").json()["total"]
    for i in range(25):
        _mk_item(client, b, admin_id, f"פריט {i:02d}")
    total = base + 25

    r = client.get(f"/api/items/search?board_ids={b}&limit=10").json()
    assert len(r["items"]) == 10, "the endpoint ignored the page size"
    assert r["total"] == total and r["has_more"] is True

    nxt = client.get(f"/api/items/search?board_ids={b}&limit=10&offset=10").json()
    assert len(nxt["items"]) == 10
    assert {i["id"] for i in nxt["items"]}.isdisjoint({i["id"] for i in r["items"]}), \
        "the second page repeated the first"

    # walk to the end: the last page is short and says there is no more
    seen, off = set(), 0
    while True:
        page = client.get(f"/api/items/search?board_ids={b}&limit=10&offset={off}").json()
        seen |= {i["id"] for i in page["items"]}
        if not page["has_more"]:
            break
        off += 10
    assert len(seen) == total, "paging did not reach every item exactly once"


def test_the_picker_filters(client, admin_id, guinea_id):
    b = _mk_board(client, admin_id, "לוח סינון")
    a1 = _mk_item(client, b, admin_id, "אלפא")
    _mk_item(client, b, admin_id, "ביתא")
    client.patch(f"/api/tasks/{a1}?user_id={admin_id}", json={"status": "done"})
    client.post(f"/api/boards/{b}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    client.post(f"/api/tasks/{a1}/assignees", json={"actor_id": admin_id, "user_id": guinea_id})

    by_name = client.get(f"/api/items/search?board_ids={b}&q=אלפ").json()["items"]
    assert [i["title"] for i in by_name] == ["אלפא"]
    by_status = client.get(f"/api/items/search?board_ids={b}&status=done").json()["items"]
    assert [i["id"] for i in by_status] == [a1]
    by_person = client.get(f"/api/items/search?board_ids={b}&assignee={guinea_id}",
                           headers={"X-CityOS-User": str(admin_id)}).json()["items"]
    assert [i["id"] for i in by_person] == [a1]


def test_the_picker_cannot_search_boards_you_cannot_see(client, admin_id):
    """It took no actor and checked nothing, so it returned titles from any board."""
    b = _mk_board(client, admin_id, "לוח סגור")
    _mk_item(client, b, admin_id, "סודי")
    email = "picker.outsider@cityos.test"
    for u in client.get("/api/users").json():
        if u.get("email") == email:
            uid = u["id"]; break
    else:
        uid = client.post("/api/users", json={"actor_id": admin_id, "name": "זר",
                                              "email": email, "role": "member"}).json()["id"]
    client.delete(f"/api/boards/1/members/{uid}?actor_id={admin_id}")
    r = client.get(f"/api/items/search?board_ids={b}&q=סודי",
                   headers={"X-CityOS-User": str(uid)}).json()
    assert r["items"] == [], "items leaked from a board the caller cannot open"
