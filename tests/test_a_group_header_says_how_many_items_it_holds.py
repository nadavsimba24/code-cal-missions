"""Every group on the board arrives knowing its own size, and the sizes add up.

GET /api/boards/{id} carries `group_counts` beside `item_count` — a map of
{"<group_id>": n} with one entry per group of the board. It exists because of
what a group header could count before it: the rows it had been sent. Past
FILTER_CLIENT_MAX the board answers with no rows at all and the browser pages
them in as it scrolls, so the header printed a number that climbed while the
person scrolled, with a "+" beside it admitting it was only a lower bound. The
answer was not to hide the plus but to know the number, so the count is taken
in SQL — one GROUP BY — and sent on every board open, paged or not.

Four properties are pinned here, and each of them breaks quietly.

**The values sum to `item_count`.** The two numbers land on the same screen,
one above the other: a header saying 1,976 over groups that add up to 1,974
gives the reader no way to tell which of the two lied. They are kept honest by
being one filter — `_visible_item_criteria`, shared by `_board_item_count` and
`_board_group_counts` — so every test below asks for both numbers at once and
refuses to accept them unless they agree. That is what `_counts` does.

**Every group is in the map, the empty ones at 0.** An absent key cannot be
read: "none" and "the server did not say" would look identical, and a browser
that guessed wrong would either print nothing over a full group or 0 over one
it had simply not been told about.

**Items that belong to no group of this board go to "null"** — the id the
board's synthetic "ללא קבוצה" heading carries. An item can hold no group at all
(a public form submits one that way) or a group that went away under it, and
counting those anywhere else, or not at all, is exactly the case where the
headers stop adding up to the board's own total. The key is there only when it
holds something.

**And the permission cut applies to both numbers.** This is the one that is not
cosmetic. An item a member was deliberately not let into — a "none" override, or
simply an item an `assigned_only` member is not assigned to — must be invisible
in the group's number as surely as it is missing from the group's rows. A header
reading 12 over eleven rows tells that member an item exists, who put it there
and roughly when; the count is per reader for that reason, and a count cached
per board rather than per reader would pass every single-user test in this file.
"""
import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from conftest import join_primary_env


def AS(uid):
    return {"X-CityOS-User": str(uid)}


@pytest.fixture
def boards(client, admin_id):
    """Boards a test makes, taken away again when it ends.

    The suite runs repeatedly against one seeded temp DB, so a board left
    behind is left behind for every later test in the same process — and these
    tests count things. Deleting the board takes its groups, its items and any
    per-item override with it, which is everything they touch. Nothing here
    ever writes to a board it did not create.
    """
    made = []
    try:
        yield made
    finally:
        for bid in reversed(made):
            # bulk-inserted rows go first: delete_board walks what it finds, and
            # these tests put up to a thousand rows on one board.
            with Session(cityos_main.engine) as db:
                db.query(cityos_main.Task).filter(cityos_main.Task.board_id == bid)\
                  .delete(synchronize_session=False)
                db.commit()
            client.delete(f"/api/boards/{bid}", headers=AS(admin_id))


def _board(client, admin_id, made, name):
    r = client.post("/api/boards", headers=AS(admin_id), json={"name": name})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    made.append(bid)
    return bid


def _group(client, admin_id, bid, name):
    r = client.post("/api/groups", headers=AS(admin_id),
                    json={"board_id": bid, "name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _item(client, admin_id, bid, title, **extra):
    r = client.post("/api/tasks", headers=AS(admin_id),
                    json={"board_id": bid, "title": title, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _board_json(client, bid, uid):
    r = client.get(f"/api/boards/{bid}", headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _counts(client, bid, uid):
    """This reader's `group_counts`, having first insisted that they add up to
    the same reader's `item_count`.

    Every test in this file goes through here, so the sum is re-checked after
    every single thing one of them does — which is the point: the breakage this
    guards against is one count learning about an item the other does not.
    """
    b = _board_json(client, bid, uid)
    counts = b["group_counts"]
    assert isinstance(counts, dict), counts
    assert all(isinstance(k, str) for k in counts), f"a key is not a string: {counts}"
    assert sum(counts.values()) == b["item_count"], (
        f"the groups add up to {sum(counts.values())} and the board says "
        f"{b['item_count']} — the two numbers are printed on one screen")
    # every group of the board is accounted for, and nothing else is
    gids = {str(g["id"]) for g in b["groups"]}
    assert gids <= set(counts), f"groups {gids - set(counts)} have no count at all"
    assert set(counts) - gids <= {"null"}, f"a count for something that is not a group: {counts}"
    return counts


def _with(client, admin_id, uid, bid, role="editor"):
    """Put somebody on the board in the given role, the way an admin does."""
    join_primary_env(client, uid)
    r = client.post(f"/api/boards/{bid}/members", headers=AS(admin_id),
                    json={"user_id": uid, "role": role})
    assert r.status_code == 200, r.text


# ── the shape of the map ──────────────────────────────────────────────────

def test_every_group_of_the_board_comes_back_with_a_count(client, admin_id, boards):
    """A new board has three groups and three starter items, all in the first
    one. So the map is exactly three keys, they are the board's own group ids
    as strings, and only one of them is non-zero."""
    bid = _board(client, admin_id, boards, "ספירת קבוצות")
    b = _board_json(client, bid, admin_id)
    gids = [g["id"] for g in b["groups"]]
    assert len(gids) == 3, b["groups"]
    counts = _counts(client, bid, admin_id)
    assert set(counts) == {str(g) for g in gids}, counts
    assert counts[str(gids[0])] == b["item_count"]


def test_an_empty_group_is_present_with_zero_rather_than_missing(client, admin_id, boards):
    """"Not in the map" and "0" would be the same thing to a header that reads
    the map with a default, and nothing at all to one that does not. A group
    nobody has filled in yet is the ordinary case on a new board, so this is
    the state most group headers are drawn in."""
    bid = _board(client, admin_id, boards, "קבוצה ריקה")
    gid = _group(client, admin_id, bid, "ריקה לגמרי")
    counts = _counts(client, bid, admin_id)
    assert str(gid) in counts, f"an empty group was left out of the map: {counts}"
    assert counts[str(gid)] == 0

    # and it stops being zero the moment something is put in it, without any
    # other group's number moving
    before = dict(counts)
    _item(client, admin_id, bid, "פריט ראשון", group_id=gid)
    after = _counts(client, bid, admin_id)
    assert after[str(gid)] == 1
    assert {k: v for k, v in after.items() if k != str(gid)} == \
           {k: v for k, v in before.items() if k != str(gid)}


def test_the_counts_follow_the_items_from_one_group_to_another(client, admin_id, boards):
    """The number is per group, not per board divided three ways. Items are
    created into named groups here and each header has to answer for its own."""
    bid = _board(client, admin_id, boards, "ספירה לפי קבוצה")
    a = _group(client, admin_id, bid, "א")
    b_ = _group(client, admin_id, bid, "ב")
    for i in range(4):
        _item(client, admin_id, bid, f"א{i}", group_id=a)
    for i in range(2):
        _item(client, admin_id, bid, f"ב{i}", group_id=b_)
    counts = _counts(client, bid, admin_id)
    assert counts[str(a)] == 4 and counts[str(b_)] == 2, counts


def test_below_the_threshold_each_count_matches_the_rows_actually_sent(client, admin_id, boards):
    """While the rows still travel there are two answers in one response to
    "how big is this group", and they are not allowed to disagree either — the
    browser draws the header from one and the rows from the other."""
    bid = _board(client, admin_id, boards, "כותרת מול שורות")
    gid = _group(client, admin_id, bid, "קבוצה נוספת")
    for i in range(3):
        _item(client, admin_id, bid, f"פריט {i}", group_id=gid)
    b = _board_json(client, bid, admin_id)
    assert b["item_count"] <= b["filter_client_max"], "this board is meant to be small"
    from collections import Counter
    drawn = Counter(str(t.get("group_id")) for t in b["tasks"] if not t.get("parent_id"))
    assert all(b["group_counts"][k] == drawn.get(k, 0) for k in b["group_counts"]), \
        f"headers {b['group_counts']} over rows {dict(drawn)}"


# ── past the paging threshold, where the counts are the only answer ───────

def test_a_board_past_the_paging_threshold_still_says_what_each_group_holds(
        client, admin_id, boards):
    """The reason the feature exists. Above FILTER_CLIENT_MAX the board answers
    with `tasks: []` and the browser pages its rows in fifty at a time, so the
    group headers have nothing in front of them to count — this map is the only
    thing up there that knows.

    The board is built past the real threshold rather than by moving the
    threshold, because the threshold is what decides that `tasks` is empty and
    this test is about the case where it is. The thousand rows go in with one
    bulk insert: they are being counted, not read, and a thousand POSTs would
    put a minute into the suite to prove the same thing.
    """
    bid = _board(client, admin_id, boards, "לוח מעל הסף")
    b = _board_json(client, bid, admin_id)
    gids = [g["id"] for g in b["groups"]]
    start = dict(b["group_counts"])
    assert b["item_count"] <= b["filter_client_max"], "it is meant to start small"

    bulk = cityos_main.FILTER_CLIENT_MAX + 10 - b["item_count"]
    with Session(cityos_main.engine) as db:
        db.bulk_insert_mappings(cityos_main.Task, [
            {"board_id": bid, "group_id": gids[i % len(gids)], "title": f"המוני {i}",
             "position": i, "created_by": admin_id} for i in range(bulk)])
        db.commit()

    big = _board_json(client, bid, admin_id)
    assert big["item_count"] > big["filter_client_max"], big["item_count"]
    assert big["tasks"] == [], "the rows were supposed to stay home up here"
    counts = _counts(client, bid, admin_id)           # …and they still add up
    assert set(counts) == {str(g) for g in gids}, counts
    # each group gained its share, and no header is left reading what it was
    # before the board grew
    for i, g in enumerate(gids):
        share = len(range(i, bulk, len(gids)))
        assert counts[str(g)] == start[str(g)] + share, (g, counts, start)
    assert all(v > 0 for v in counts.values()), counts


# ── the items that belong to no group of this board ──────────────────────

def test_an_item_with_no_group_at_all_is_counted_under_null(client, admin_id, boards):
    """An item created without a group — which is what a public form submits —
    keeps group_id NULL, and the board draws it under a heading of its own
    whose id is null. "null" is the key a browser lookup on that id produces,
    and it is the one key in the map that is not a group of the board."""
    bid = _board(client, admin_id, boards, "ללא קבוצה")
    assert "null" not in _counts(client, bid, admin_id), "nothing is orphaned yet"
    tid = _item(client, admin_id, bid, "פריט יתום")
    with Session(cityos_main.engine) as db:
        assert db.query(cityos_main.Task.group_id)\
                 .filter(cityos_main.Task.id == tid).scalar() is None
    counts = _counts(client, bid, admin_id)     # the sum is the assertion here
    assert counts["null"] == 1, counts


def test_the_null_key_stays_away_while_every_item_has_a_group(client, admin_id, boards):
    """It is there only when it holds something: a board where every item is
    filed has no "ללא קבוצה" heading, and a 0 under that key would make the
    browser draw an empty one."""
    bid = _board(client, admin_id, boards, "הכול מסודר")
    gid = _group(client, admin_id, bid, "מסודרת")
    _item(client, admin_id, bid, "פריט מסודר", group_id=gid)
    assert "null" not in _counts(client, bid, admin_id)


def test_an_item_whose_group_was_deleted_under_it_moves_into_the_null_bucket(
        client, admin_id, boards):
    """Deleting a group does not delete its items — they fall back to "ללא
    קבוצה". So the board's total does not move at all, and the only thing that
    changes is which header the items are counted under. A map that simply
    dropped the gone group's entry would lose them from the sum."""
    bid = _board(client, admin_id, boards, "קבוצה שנמחקה")
    gid = _group(client, admin_id, bid, "זמנית")
    for i in range(3):
        _item(client, admin_id, bid, f"בזמנית {i}", group_id=gid)
    before = _board_json(client, bid, admin_id)["item_count"]
    assert _counts(client, bid, admin_id)[str(gid)] == 3

    r = client.delete(f"/api/groups/{gid}", headers=AS(admin_id))
    assert r.status_code == 200, r.text
    counts = _counts(client, bid, admin_id)
    assert str(gid) not in counts, "a group that is gone still has a header"
    assert counts["null"] == 3, counts
    assert _board_json(client, bid, admin_id)["item_count"] == before, \
        "deleting a group lost its items from the board's total"


def test_a_group_does_not_count_an_item_that_lives_on_another_board(
        client, admin_id, boards):
    """group_id is a plain column and nothing stops it naming a group of a
    different board — an import, a botched move, or simply a row older than
    whatever rule would have prevented it. The count is taken over one board's
    items, so the stray row must be invisible on the board that owns the group
    and orphaned on the board that owns the item. Counting it where the group
    lives would be an item appearing on a board nobody put it on.

    The state is made directly: no endpoint will file an item under another
    board's group, which is exactly why the count has to survive meeting one.
    Both boards belong to this test and are deleted with it.
    """
    owner = _board(client, admin_id, boards, "בעלת הקבוצה")
    other = _board(client, admin_id, boards, "הלוח השני")
    gid = _group(client, admin_id, owner, "קבוצה מושאלת")
    _item(client, admin_id, owner, "פריט שלה", group_id=gid)
    stray = _item(client, admin_id, other, "פריט זר")

    owner_before = _counts(client, owner, admin_id)
    with Session(cityos_main.engine) as db:
        db.query(cityos_main.Task).filter(cityos_main.Task.id == stray)\
          .update({"group_id": gid})
        db.commit()

    assert _counts(client, owner, admin_id) == owner_before, \
        "a foreign board's item was counted into this group"
    # and on its own board it is an item with no group of this board, so it is
    # in the orphan bucket — still inside the sum, which _counts just checked
    assert _counts(client, other, admin_id)["null"] == 1


# ── the permission cut, which both numbers take together ─────────────────

def test_an_item_closed_to_a_reader_is_in_neither_its_boards_count_nor_its_groups(
        client, admin_id, guinea_id, boards):
    """The privacy half of the feature. A "none" override takes the item off
    the board for that reader, and a header still counting it would tell them
    an item is there, in that group, that they were deliberately not let into.
    The admin's own numbers must not move at the same time — the count is per
    reader, and one cached per board would fail exactly here."""
    bid = _board(client, admin_id, boards, "פריט סגור")
    _with(client, admin_id, guinea_id, bid)
    gid = _group(client, admin_id, bid, "קבוצה עם סוד")
    open_items = [_item(client, admin_id, bid, f"גלוי {i}", group_id=gid) for i in range(2)]
    secret = _item(client, admin_id, bid, "סודי", group_id=gid)

    admin_counts = _counts(client, bid, admin_id)
    assert _counts(client, bid, guinea_id) == admin_counts, "they start out equal"
    assert admin_counts[str(gid)] == 3

    r = client.post(f"/api/tasks/{secret}/permissions", headers=AS(admin_id),
                    json={"user_id": guinea_id, "perm": "none"})
    assert r.status_code == 200, r.text
    try:
        theirs = _counts(client, bid, guinea_id)        # the sum is re-checked
        assert theirs[str(gid)] == 2, theirs
        assert _counts(client, bid, admin_id) == admin_counts, \
            "the admin lost an item that was hidden from somebody else"
        # the rows agree with the header they are under
        rows = [t for t in _board_json(client, bid, guinea_id)["tasks"]
                if t.get("group_id") == gid]
        assert {t["id"] for t in rows} == set(open_items), rows
    finally:
        client.post(f"/api/tasks/{secret}/permissions", headers=AS(admin_id),
                    json={"user_id": guinea_id, "perm": None})
    # clearing the override puts it back into both of their numbers at once
    assert _counts(client, bid, guinea_id) == admin_counts


def test_an_override_that_is_not_none_leaves_the_item_in_its_groups_count(
        client, admin_id, guinea_id, boards):
    """Only "none" hides. An override reading "view" narrows what may be done
    to the row, not whether it is there — and the SQL reads the same JSON key
    for both, so the two are one word apart."""
    bid = _board(client, admin_id, boards, "הרשאת צפייה")
    _with(client, admin_id, guinea_id, bid)
    gid = _group(client, admin_id, bid, "קבוצה לצפייה")
    tid = _item(client, admin_id, bid, "לצפייה בלבד", group_id=gid)
    before = _counts(client, bid, guinea_id)
    r = client.post(f"/api/tasks/{tid}/permissions", headers=AS(admin_id),
                    json={"user_id": guinea_id, "perm": "view"})
    assert r.status_code == 200, r.text
    try:
        assert _counts(client, bid, guinea_id) == before
    finally:
        client.post(f"/api/tasks/{tid}/permissions", headers=AS(admin_id),
                    json={"user_id": guinea_id, "perm": None})


def test_an_assigned_only_member_counts_only_the_items_they_are_assigned(
        client, admin_id, guinea_id, boards):
    """The other branch of the same predicate, and the one where the default is
    closed: an `assigned_only` member sees only the items they are named on,
    and every other item does not exist for them — not as a row, and not as
    part of a number over a group they share.

    This branch is separate SQL from the override test above (it is
    `_assigned_only_sql`, a subquery over the board's permission column), so a
    group count that forgot it would leak the size of a board to the one role
    the board was narrowed for.
    """
    bid = _board(client, admin_id, boards, "משויכים בלבד")
    _with(client, admin_id, guinea_id, bid, role="assigned_only")
    mine_g = _group(client, admin_id, bid, "קבוצה משותפת")
    theirs_g = _group(client, admin_id, bid, "קבוצה זרה")
    mine = _item(client, admin_id, bid, "שלי", group_id=mine_g)
    _item(client, admin_id, bid, "לא שלי", group_id=mine_g)
    _item(client, admin_id, bid, "זר", group_id=theirs_g)

    # before anything is assigned to them the board is empty for them, headers
    # and total alike
    counts = _counts(client, bid, guinea_id)
    assert set(counts.values()) == {0}, counts
    assert _board_json(client, bid, guinea_id)["item_count"] == 0

    r = client.post(f"/api/tasks/{mine}/assignees", headers=AS(admin_id),
                    json={"user_id": guinea_id, "action": "add"})
    assert r.status_code == 200, r.text
    counts = _counts(client, bid, guinea_id)
    assert counts[str(mine_g)] == 1, counts
    assert counts[str(theirs_g)] == 0, counts
    assert _board_json(client, bid, guinea_id)["item_count"] == 1
    # the admin, meanwhile, still sees the whole board
    admin_counts = _counts(client, bid, admin_id)
    assert admin_counts[str(mine_g)] == 2 and admin_counts[str(theirs_g)] == 1


# ── what is not an item of the group ─────────────────────────────────────

def test_an_archived_item_is_in_no_group_count(client, admin_id, boards):
    """Archived is not deleted and the row is still there with its group on it,
    so a count that forgot `is_archived` would read perfectly — just high."""
    bid = _board(client, admin_id, boards, "ארכיון")
    gid = _group(client, admin_id, bid, "קבוצת ארכיון")
    tid = _item(client, admin_id, bid, "לארכיון", group_id=gid)
    assert _counts(client, bid, admin_id)[str(gid)] == 1
    # archiving has no REST endpoint of its own — the flag is set by the AI
    # tool path and nowhere else — so the state is made here directly, on a
    # board this test owns and deletes.
    with Session(cityos_main.engine) as db:
        db.query(cityos_main.Task).filter(cityos_main.Task.id == tid)\
          .update({"is_archived": True})
        db.commit()
    assert _counts(client, bid, admin_id)[str(gid)] == 0


def test_an_item_in_the_bin_is_in_no_group_count_until_it_is_restored(
        client, admin_id, boards):
    """The bin is a soft delete, so the row keeps its group_id and comes back
    to the same header on a restore. The group count is an aggregate over a
    column rather than a query for entities, which is a different path through
    the soft-delete machinery than the rows take."""
    bid = _board(client, admin_id, boards, "סל מחזור")
    gid = _group(client, admin_id, bid, "קבוצת מחיקה")
    tid = _item(client, admin_id, bid, "למחיקה", group_id=gid)
    assert _counts(client, bid, admin_id)[str(gid)] == 1
    r = client.delete(f"/api/tasks/{tid}", headers=AS(admin_id))
    assert r.status_code == 200, r.text
    assert _counts(client, bid, admin_id)[str(gid)] == 0
    r = client.post(f"/api/tasks/{tid}/restore", headers=AS(admin_id))
    assert r.status_code == 200, r.text
    assert _counts(client, bid, admin_id)[str(gid)] == 1


def test_a_sub_item_is_not_counted_in_its_parents_group(client, admin_id, boards):
    """A sub-item inherits its parent's group and is not a row of the board: it
    is drawn nested under the parent, not under the group heading. Counting it
    there would make a group of nine items with three sub-items each report
    thirty-six, and the board's own total would be the first thing to disagree."""
    bid = _board(client, admin_id, boards, "תתי פריטים")
    gid = _group(client, admin_id, bid, "קבוצת אב")
    parent = _item(client, admin_id, bid, "פריט אב", group_id=gid)
    before = _counts(client, bid, admin_id)
    for i in range(3):
        _item(client, admin_id, bid, f"תת {i}", parent_id=parent)
    assert _counts(client, bid, admin_id) == before
