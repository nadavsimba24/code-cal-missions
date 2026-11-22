"""A board too big to draw keeps its rows at home — and says how many there are.

GET /api/boards/{id} used to serialize every item of a board. On the imported
board of 21,187 items that was 28.7MB and 5.6 seconds of server time, and the
browser threw every byte of it away: past FILTER_CLIENT_MAX it does not filter
locally at all, it fetches its rows fifty at a time from
POST /api/boards/{id}/items/query. So above the threshold the board now answers
with `tasks: []` and `link_display: {}`, and it carries `item_count` — the true
number of top-level items this particular reader has on it.

Three rules are pinned here, and each one of them breaks in a way nobody would
notice until a real board failed in front of somebody.

**`item_count` has to equal the `total` that /items/query reports** for an
unfiltered query by the same caller. The number the screen shows and the rows
behind it now come from two different queries down two different code paths:
one counts in SQL, the other loads the rows and filters them in Python. They
agree today, and every way they could stop agreeing is a rule about which items
count at all — a sub-item, an archived item, one in the bin, one closed to this
reader by a "none" override. So each of those is asked of both, and the two
answers are compared rather than compared to a number this file made up.

**Everything that is not a row still travels.** The browser cannot draw a
single paged row before it has the board's columns, groups, statuses,
priorities, members, col_perms and filter_client_max — the rows arrive later
and arrive bare. A regression that dropped one of them along with `tasks` would
pass every test that only looks at `tasks`, and would be discovered as a board
that renders nothing.

**The comparison is strictly greater.** A board sitting exactly on the
threshold filters locally and therefore needs its rows. Sending it none would
blank a 1000-item board while the server believed it was behaving as designed —
the off-by-one is the whole reason that case is written out separately below.

FILTER_CLIENT_MAX is read from the environment once, at import, so the tests
that need a board "above the threshold" move the threshold rather than create a
thousand items — the same monkeypatch-the-module-constant trick
test_filter_edge_cases.py uses for FILTER_COLUMN_POLICY.
"""
import pathlib

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from conftest import join_primary_env

ROOT = pathlib.Path(__file__).resolve().parent.parent


def AS(uid):
    return {"X-CityOS-User": str(uid)}


# The keys the browser needs before it can draw anything at all. `tasks` and
# `link_display` are deliberately not in here — those are the two that empty.
MUST_TRAVEL = ("columns", "groups", "statuses", "priorities", "members",
               "col_perms", "filter_client_max", "my_role", "views",
               "col_widths", "col_order", "col_hidden", "sub_cols",
               "retention_days", "owners", "filter_column_policy")


@pytest.fixture
def boards(client, admin_id):
    """Boards a test makes, taken away again when it ends.

    The suite runs repeatedly against one seeded temp DB, so a test that leaves
    a board behind leaves it behind for every later run of the same process.
    Deleting the board takes its items, its groups and any per-item permission
    override with it, which is everything these tests touch.
    """
    made = []
    try:
        yield made
    finally:
        for bid in reversed(made):
            client.delete(f"/api/boards/{bid}", headers=AS(admin_id))


def _board(client, admin_id, made, name):
    r = client.post("/api/boards", json={"actor_id": admin_id, "name": name})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    made.append(bid)
    return bid


def _item(client, admin_id, bid, title, **extra):
    r = client.post("/api/tasks", json={"actor_id": admin_id, "board_id": bid,
                                        "title": title, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _board_json(client, bid, uid):
    r = client.get(f"/api/boards/{bid}", headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _query_total(client, bid, uid):
    """What /items/query answers as `total` for a query with nothing filtered —
    the number item_count claims to be."""
    r = client.post(f"/api/boards/{bid}/items/query",
                    json={"filter": {"operator": "and", "rules": []},
                          "ids_only": True},
                    headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()["total"]


def _agree(client, bid, uid):
    """The board's item_count, having first insisted that /items/query agrees
    with it. Returned so the test can also say what the number ought to be."""
    count = _board_json(client, bid, uid)["item_count"]
    total = _query_total(client, bid, uid)
    assert count == total, (
        f"the board says {count} items and the paged query says {total} — "
        "the two numbers land on the same screen")
    return count


def _with_guinea(client, admin_id, guinea_id, made, name):
    """A board the guinea is an editor of, so both readers can be compared."""
    bid = _board(client, admin_id, made, name)
    join_primary_env(client, guinea_id)
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"},
                    headers=AS(admin_id))
    assert r.status_code == 200, r.text
    return bid


# ── the count is the same number the rows are paged out of ────────────────
def test_the_item_count_is_the_number_the_paged_query_reports(client, admin_id, boards):
    """The ordinary board, where nobody has a per-item override of any kind —
    worth saying out loud because the permission clause of the count is written
    in SQL against a JSON key that is absent on every row here, and an absent
    key extracts as NULL. A comparison that got that wrong would count nothing
    at all on the overwhelming majority of boards."""
    bid = _board(client, admin_id, boards, "ספירה א")
    before = _agree(client, bid, admin_id)
    for i in range(4):
        _item(client, admin_id, bid, f"פריט נוסף {i}")
    assert _agree(client, bid, admin_id) == before + 4


def test_below_the_threshold_the_count_is_also_the_number_of_rows_sent(client, admin_id, boards):
    """While the rows do travel, there are two answers to "how big is this
    board" in one response, and they are not allowed to disagree either."""
    bid = _board(client, admin_id, boards, "ספירה ב")
    _item(client, admin_id, bid, "פריט")
    b = _board_json(client, bid, admin_id)
    assert b["item_count"] <= b["filter_client_max"], "this board is meant to be small"
    assert len(b["tasks"]) == b["item_count"]


def test_an_item_closed_to_this_reader_is_in_neither_count(client, admin_id, guinea_id, boards):
    """A "none" override is the one part of the count that is not a plain
    COUNT, and the SQL has to take out exactly the items _item_perm takes out
    of the query's rows — no more and no less. An item somebody closed is gone
    from the board for that reader, so it is gone from their number too."""
    bid = _with_guinea(client, admin_id, guinea_id, boards, "ספירה סגורה")
    open_to_all = _agree(client, bid, guinea_id)
    tid = _item(client, admin_id, bid, "פריט סגור")
    assert _agree(client, bid, guinea_id) == open_to_all + 1

    r = client.post(f"/api/tasks/{tid}/permissions", headers=AS(admin_id),
                    json={"user_id": guinea_id, "perm": "none"})
    assert r.status_code == 200, r.text
    assert _agree(client, bid, guinea_id) == open_to_all

    # and clearing the override brings it back to both numbers at once
    client.post(f"/api/tasks/{tid}/permissions", headers=AS(admin_id),
                json={"user_id": guinea_id, "perm": None})
    assert _agree(client, bid, guinea_id) == open_to_all + 1


def test_an_override_that_is_not_none_leaves_the_item_counted(client, admin_id, guinea_id, boards):
    """Only "none" hides an item. An override reading "view" is a narrowing of
    what may be done to the row, not of whether it is there — and the SQL reads
    the same JSON key for both, so the two are one character apart."""
    bid = _with_guinea(client, admin_id, guinea_id, boards, "ספירה צפייה")
    tid = _item(client, admin_id, bid, "פריט לצפייה בלבד")
    before = _agree(client, bid, guinea_id)
    client.post(f"/api/tasks/{tid}/permissions", headers=AS(admin_id),
                json={"user_id": guinea_id, "perm": "view"})
    assert _agree(client, bid, guinea_id) == before


def test_an_archived_item_is_in_neither_count(client, admin_id, boards):
    bid = _board(client, admin_id, boards, "ספירה ארכיון")
    tid = _item(client, admin_id, bid, "פריט לארכיון")
    before = _agree(client, bid, admin_id)
    # Archiving has no REST endpoint of its own — the flag is set by the AI
    # tool path and nowhere else — so the state is made here directly, the way
    # test_dashboard_sources_and_mapping.py does it. The board belongs to this
    # test and is deleted with it, so nothing shared is being mutated.
    with Session(cityos_main.engine) as db:
        db.query(cityos_main.Task).filter(cityos_main.Task.id == tid)\
          .update({"is_archived": True})
        db.commit()
    assert _agree(client, bid, admin_id) == before - 1


def test_an_item_in_the_bin_is_in_neither_count(client, admin_id, boards):
    """An item somebody deleted is in the bin, not on the board. The count is
    an aggregate over a column rather than a query for entities, which is a
    different path through the soft-delete machinery than the one the rows take
    — so "deleted" is asked of it explicitly here. A board reporting every item
    anybody ever deleted on it would also page itself for no reason."""
    bid = _board(client, admin_id, boards, "ספירה סל")
    tid = _item(client, admin_id, bid, "פריט למחיקה")
    before = _agree(client, bid, admin_id)
    r = client.delete(f"/api/tasks/{tid}", headers=AS(admin_id))
    assert r.status_code == 200, r.text
    assert _agree(client, bid, admin_id) == before - 1

    # …and restoring it from the bin puts it back into both numbers
    r = client.post(f"/api/tasks/{tid}/restore", headers=AS(admin_id))
    assert r.status_code == 200, r.text
    assert _agree(client, bid, admin_id) == before


def test_a_sub_item_is_not_an_item_of_the_board(client, admin_id, boards):
    """`item_count` is what the browser reads to decide whether to page, and
    the paging is over top-level rows: a board of 900 items with two sub-items
    each would otherwise count 2,700 and page a board that fits on screen."""
    bid = _board(client, admin_id, boards, "ספירה תתי")
    parent = _item(client, admin_id, bid, "פריט אב")
    before = _agree(client, bid, admin_id)
    for i in range(3):
        _item(client, admin_id, bid, f"תת פריט {i}", parent_id=parent)
    assert _agree(client, bid, admin_id) == before


def test_two_readers_of_one_board_each_get_their_own_count(client, admin_id, guinea_id, boards):
    """One person's number must never leak items the other cannot see. The
    count takes the reader as an argument for exactly this, and a count cached
    per board rather than per reader would pass every single-user test here."""
    bid = _with_guinea(client, admin_id, guinea_id, boards, "ספירה שניים")
    closed = [_item(client, admin_id, bid, f"סגור {i}") for i in range(2)]
    _item(client, admin_id, bid, "פתוח")
    both = _agree(client, bid, admin_id)
    assert _agree(client, bid, guinea_id) == both

    for tid in closed:
        client.post(f"/api/tasks/{tid}/permissions", headers=AS(admin_id),
                    json={"user_id": guinea_id, "perm": "none"})
    assert _agree(client, bid, admin_id) == both, "the admin lost items that were not hidden from him"
    assert _agree(client, bid, guinea_id) == both - 2


# ── above the threshold: no rows, everything else ─────────────────────────
def test_a_board_above_the_threshold_sends_no_rows_and_no_link_display(
        client, admin_id, boards, monkeypatch):
    """The change itself: past the threshold the browser pages its rows in from
    /items/query and never reads `tasks`, so `tasks` stops being sent. The same
    board is read twice, once on each side of the threshold, so what is being
    compared is the threshold and nothing else."""
    bid = _board(client, admin_id, boards, "לוח גדול")
    _item(client, admin_id, bid, "פריט")
    small = _board_json(client, bid, admin_id)
    assert small["tasks"], "the board has to have rows for losing them to mean anything"

    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", small["item_count"] - 1)
    big = _board_json(client, bid, admin_id)
    assert big["tasks"] == []
    assert big["link_display"] == {}
    # and the count is still the truth, which is the only thing up here saying
    # the board is not empty
    assert big["item_count"] == small["item_count"]
    assert _query_total(client, bid, admin_id) == big["item_count"]


def test_the_link_display_that_empties_is_one_that_had_something_in_it(
        client, admin_id, boards, monkeypatch):
    """`link_display == {}` is true of a board with no connect column at all,
    so on its own it proves nothing. This board has a connect column told to
    show a field of the linked record, and a map with an entry in it below the
    threshold — the map is built from the serialized rows, and above the
    threshold there are none to build it from."""
    target = _board(client, admin_id, boards, "יעד תצוגה")
    cols = _board_json(client, target, admin_id)["columns"] + [
        {"type": "text", "title": "שם מלא"}]
    assert client.patch(f"/api/boards/{target}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200
    disp = next(c["id"] for c in _board_json(client, target, admin_id)["columns"]
                if c["title"] == "שם מלא")
    rec = _item(client, admin_id, target, "בית דגן",
                custom_fields={disp: "בית דגן - מועצה מקומית"})

    src = _board(client, admin_id, boards, "מקור תצוגה")
    cols = _board_json(client, src, admin_id)["columns"] + [
        {"type": "connect", "title": "קישור",
         "connect": {"board_ids": [target], "multiple": True, "display_field": disp}}]
    assert client.patch(f"/api/boards/{src}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200
    cid = next(c["id"] for c in _board_json(client, src, admin_id)["columns"]
               if c["type"] == "connect")
    _item(client, admin_id, src, "מקור", custom_fields={cid: [rec]})

    small = _board_json(client, src, admin_id)
    assert small["link_display"].get(cid, {}).get(str(rec)) == "בית דגן - מועצה מקומית"

    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", small["item_count"] - 1)
    big = _board_json(client, src, admin_id)
    assert big["tasks"] == [] and big["link_display"] == {}
    # the column itself still travels — only the per-row override map is gone
    assert any(c["id"] == cid for c in big["columns"])


def test_a_board_above_the_threshold_still_carries_everything_but_the_rows(
        client, admin_id, guinea_id, boards, monkeypatch):
    """The browser needs all of this before it can draw one paged row, so a
    regression that dropped a key along with the rows would be invisible until
    a large board rendered nothing."""
    bid = _with_guinea(client, admin_id, guinea_id, boards, "לוח גדול מלא")
    _item(client, admin_id, bid, "פריט")
    small = _board_json(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", small["item_count"] - 1)
    big = _board_json(client, bid, admin_id)

    assert set(big) == set(small), "the response changed shape above the threshold"
    for key in MUST_TRAVEL:
        if key == "filter_client_max":
            continue          # it is the number that moved; checked below
        assert big[key] == small[key], f"{key} was dropped with the rows"
    assert big["columns"] and big["groups"] and big["statuses"] and big["priorities"]
    assert big["members"] and big["col_perms"]
    # the threshold itself travels too, so the browser picks the same mode the
    # server just picked — otherwise it would filter locally over no rows
    assert big["filter_client_max"] == cityos_main.FILTER_CLIENT_MAX
    assert big["item_count"] > big["filter_client_max"]


def test_a_board_exactly_on_the_threshold_still_sends_its_rows(
        client, admin_id, boards, monkeypatch):
    """The off-by-one that would silently blank a 1000-item board: the
    comparison is strictly greater, the same one filterMode() makes in the
    browser. A board exactly on the threshold filters locally — which it can
    only do over rows it was given."""
    bid = _board(client, admin_id, boards, "לוח על הגבול")
    for i in range(3):
        _item(client, admin_id, bid, f"פריט {i}")
    count = _agree(client, bid, admin_id)

    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", count)
    b = _board_json(client, bid, admin_id)
    assert b["item_count"] == count
    assert len(b["tasks"]) == count, "a board exactly on the threshold came back blank"

    # one item past it and the rows stay home — the same board, one step over
    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", count - 1)
    assert _board_json(client, bid, admin_id)["tasks"] == []


def test_the_rows_an_item_count_promises_can_be_paged_in(client, admin_id, boards, monkeypatch):
    """The end of the feature, not the middle of it: above the threshold the
    rows are not gone, they are somewhere else. Walking /items/query has to
    yield exactly as many rows as the board said it had."""
    bid = _board(client, admin_id, boards, "לוח גדול דפדוף")
    for i in range(5):
        _item(client, admin_id, bid, f"פריט {i}")
    count = _agree(client, bid, admin_id)
    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", 2)

    b = _board_json(client, bid, admin_id)
    assert b["tasks"] == [] and b["item_count"] == count

    seen, off, guard = [], 0, 0
    while True:
        guard += 1
        assert guard < 20, "the walk does not end"
        r = client.post(f"/api/boards/{bid}/items/query", headers=AS(admin_id),
                        json={"filter": {"operator": "and", "rules": []}, "offset": off})
        assert r.status_code == 200, r.text
        d = r.json()
        seen += [t["id"] for t in d["items"]]
        if not d["has_more"]:
            break
        off = d["next_offset"]
    assert len(set(seen)) == count, f"{len(set(seen))} rows paged in, board said {count}"


# ── the other half of the bargain, in the browser ─────────────────────────
def test_the_browser_asks_the_board_how_big_it_is_instead_of_counting_the_rows():
    """len(tasks) stopped being an answer to "how big is this board" the moment
    the rows stopped travelling. A browser that still counted them would read a
    21,187-item board as empty, draw the "no items yet" screen over it, and
    never cross back into server-side filtering — which is the one path that
    could have fetched the rows."""
    src = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    i = src.index("function boardRowCount(){")
    body = src[i:src.index("\n}", i)]
    assert "item_count" in body, "the browser counts the rows it was sent"
    # and a response from an older server, which carries no count, still works
    assert "tasks" in body and "length" in body


# ── and the work is skipped, not done and thrown away ─────────────────────
@pytest.fixture
def counted():
    """Count SQL statements issued while the block runs — the same listener
    test_board_open_is_one_pass.py uses, for the same reason: the wall clock on
    this machine proves nothing, and the statement count is the thing that was
    growing with the board."""
    from sqlalchemy import event

    class Counter:
        n = 0

    c = Counter()

    def _tick(*a, **kw):
        c.n += 1

    event.listen(cityos_main.engine, "before_cursor_execute", _tick)
    try:
        yield c
    finally:
        event.remove(cityos_main.engine, "before_cursor_execute", _tick)


def test_above_the_threshold_the_cost_of_opening_stops_growing_with_the_board(
        client, admin_id, boards, counted, monkeypatch):
    """An empty `tasks` list would be a hollow fix if the rows were still being
    loaded, prefetched and serialized before being dropped — 28.7MB of JSON is
    only the part of the bill that shows up on the wire. So the test is the one
    property that was broken: past the threshold, opening a board of thirty
    items costs exactly what opening a board of ten costs."""
    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", 5)
    small = _board(client, admin_id, boards, "עלות קטנה")
    big = _board(client, admin_id, boards, "עלות גדולה")
    for i in range(7):
        _item(client, admin_id, small, f"פריט {i}")
    for i in range(27):
        _item(client, admin_id, big, f"פריט {i}")
    for bid in (small, big):
        client.get(f"/api/boards/{bid}", headers=AS(admin_id))   # warm anything per-process

    counted.n = 0
    assert _board_json(client, small, admin_id)["tasks"] == []
    cheap = counted.n
    counted.n = 0
    assert _board_json(client, big, admin_id)["tasks"] == []
    assert counted.n == cheap, (
        f"a board of 30 cost {counted.n} statements and a board of 10 cost {cheap} — "
        "the rows are still being loaded and then thrown away")
