"""כללי התאמה בהיררכיה — ארבע המשבצות, ומה נגזר מהן.

    האב מתאים | יש תת פריט מתאים | התוצאה
    כן        | כן               | האב ותתי הפריטים המתאימים בלבד
    כן        | לא               | האב בלבד
    לא        | כן               | האב כהקשר ותתי הפריטים המתאימים בלבד
    לא        | לא               | לא מוצגים

Two things fall out of the table that are easy to get wrong in opposite
directions, and each has its own cases below.

A parent that matches still shows only the sub-items that match. The second
row is where that becomes visible — a matching parent with no matching child
shows NO children, not all of them. A cut is a cut all the way down; showing
the rest under a matching parent would answer a different question on every
row depending on whether its parent happened to qualify.

A parent present only because of its children is marked as such. The third row
exists to say WHERE the matches are, and an unmarked context row reads as a
row that answered the filter — which is why the counts are reported separately
too: "3 פריטים" over a list where one of them is only scaffolding is a number
the screen cannot correct.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402

from test_saved_views import _board  # noqa: E402


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _item(client, bid, uid, title, parent=None, **extra):
    body = dict({"board_id": bid, "title": title, "user_id": uid}, **extra)
    if parent is not None:
        body["parent_id"] = parent
    r = client.post("/api/tasks", json=body, headers=_h(uid))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _query(client, bid, uid, **body):
    r = client.post(f"/api/boards/{bid}/items/query",
                    json=dict({"user_id": uid, "today": "2026-10-20",
                               "tz_offset": 180}, **body), headers=_h(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _on(word):
    return {"op": "and", "rules": [{"field": "title", "op": "has", "v": word}]}


def _row(res, title):
    return next((i for i in res["items"] if i["title"] == title), None)


@pytest.fixture
def tree(client, admin_id):
    """One board, one parent per row of the table.

    "סימן" is the word the filter looks for; every other title avoids it.
    """
    bid = _board(client, admin_id)
    made = {}
    # row 1 — parent matches, a child matches
    made["both"] = _item(client, bid, admin_id, "הורה סימן א")
    made["both_hit"] = _item(client, bid, admin_id, "ילד סימן א", parent=made["both"])
    made["both_miss"] = _item(client, bid, admin_id, "ילד רגיל א", parent=made["both"])
    # row 2 — parent matches, no child does
    made["parent"] = _item(client, bid, admin_id, "הורה סימן ב")
    made["parent_kid"] = _item(client, bid, admin_id, "ילד רגיל ב", parent=made["parent"])
    # row 3 — parent does not, a child does
    made["ctx"] = _item(client, bid, admin_id, "הורה רגיל ג")
    made["ctx_hit"] = _item(client, bid, admin_id, "ילד סימן ג", parent=made["ctx"])
    made["ctx_miss"] = _item(client, bid, admin_id, "ילד רגיל ג", parent=made["ctx"])
    # row 4 — neither
    made["none"] = _item(client, bid, admin_id, "הורה רגיל ד")
    made["none_kid"] = _item(client, bid, admin_id, "ילד רגיל ד", parent=made["none"])
    return {"bid": bid, **made}


# ── the four rows ──────────────────────────────────────────────────────────
def test_parent_matches_and_a_child_matches(client, tree, admin_id):
    """האב ותתי הפריטים המתאימים בלבד."""
    r = _query(client, tree["bid"], admin_id, filter=_on("סימן"))
    row = _row(r, "הורה סימן א")
    assert row is not None
    assert [s["title"] for s in row["subtasks"]] == ["ילד סימן א"], row["subtasks"]
    assert row["context_only"] is False


def test_parent_matches_and_no_child_does(client, tree, admin_id):
    """האב בלבד — and that means no children under it, not all of them."""
    r = _query(client, tree["bid"], admin_id, filter=_on("סימן"))
    row = _row(r, "הורה סימן ב")
    assert row is not None
    assert row["subtasks"] == [], row["subtasks"]
    assert row["context_only"] is False


def test_parent_does_not_match_and_a_child_does(client, tree, admin_id):
    """האב כהקשר ותתי הפריטים המתאימים בלבד."""
    r = _query(client, tree["bid"], admin_id, filter=_on("סימן"))
    row = _row(r, "הורה רגיל ג")
    assert row is not None, "the parent of a matching sub-item was dropped"
    assert [s["title"] for s in row["subtasks"]] == ["ילד סימן ג"]
    assert row["context_only"] is True, "a context row is indistinguishable from a hit"


def test_neither_matches(client, tree, admin_id):
    """לא מוצגים."""
    r = _query(client, tree["bid"], admin_id, filter=_on("סימן"))
    assert _row(r, "הורה רגיל ד") is None
    assert "ילד רגיל ד" not in [s["title"] for i in r["items"] for s in i["subtasks"]]


def test_the_four_rows_together(client, tree, admin_id):
    """Three parents, and the fourth absent."""
    r = _query(client, tree["bid"], admin_id, filter=_on("סימן"))
    assert {i["title"] for i in r["items"]} == {
        "הורה סימן א",      # matched, with a matching child
        "הורה סימן ב",      # matched, with none
        "הורה רגיל ג",      # context, for its matching child
    }, [i["title"] for i in r["items"]]
    # and every child shown, across all of them, is one that matched
    assert {s["title"] for i in r["items"] for s in i["subtasks"]} == {
        "ילד סימן א", "ילד סימן ג"}


# ── the counts ─────────────────────────────────────────────────────────────
def test_the_counts_separate_hits_from_context(client, tree, admin_id):
    """"3 פריטים" over a list where one is only scaffolding is a number the
    screen cannot correct."""
    r = _query(client, tree["bid"], admin_id, filter=_on("סימן"))
    assert r["matched"] == 3, "the rows returned"
    assert r["matched_own"] == 2, "the parents that answered the cut themselves"
    assert r["matched_subs"] == 2, "the sub-items that answered it"


# ── a cut is a cut all the way down ────────────────────────────────────────
def test_no_filter_at_all_shows_every_sub_item(client, tree, admin_id):
    """The narrowing is the FILTER's doing — with none, nothing is narrowed."""
    r = _query(client, tree["bid"], admin_id)
    row = _row(r, "הורה סימן א")
    assert sorted(s["title"] for s in row["subtasks"]) == ["ילד סימן א", "ילד רגיל א"]
    assert row["context_only"] is False


def test_the_search_narrows_the_hierarchy_the_same_way(client, tree, admin_id):
    """The search is a layer on the same question, so it reaches sub-items
    too — otherwise typing in the box would widen the children."""
    r = _query(client, tree["bid"], admin_id, q="סימן")
    row = _row(r, "הורה רגיל ג")
    assert row is not None and row["context_only"] is True
    assert [s["title"] for s in row["subtasks"]] == ["ילד סימן ג"]
    assert _row(r, "הורה רגיל ד") is None


# ── permissions come first, here too ───────────────────────────────────────
def test_a_sub_item_somebody_may_not_see_does_not_pull_its_parent_in(client, admin_id, guinea_id):
    """Otherwise the hierarchy is a side door: the row appears, as context,
    because of a child they are not allowed to know about."""
    bid = _board(client, admin_id, invite=[guinea_id])
    parent = _item(client, bid, admin_id, "הורה רגיל")
    hidden = _item(client, bid, admin_id, "ילד סימן", parent=parent)
    r = client.post(f"/api/tasks/{hidden}/permissions",
                    json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"},
                    headers=_h(admin_id))
    assert r.status_code == 200, r.text

    theirs = _query(client, bid, guinea_id, filter=_on("סימן"))
    assert _row(theirs, "הורה רגיל") is None, "a forbidden child pulled its parent in"
    mine = _query(client, bid, admin_id, filter=_on("סימן"))
    assert _row(mine, "הורה רגיל") is not None, "the rule is about the reader"


def test_a_hidden_sub_item_is_not_listed_under_a_parent_that_matched(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    parent = _item(client, bid, admin_id, "הורה סימן")
    hidden = _item(client, bid, admin_id, "ילד סימן", parent=parent)
    client.post(f"/api/tasks/{hidden}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"},
                headers=_h(admin_id))
    row = _row(_query(client, bid, guinea_id, filter=_on("סימן")), "הורה סימן")
    assert row is not None and row["subtasks"] == []


# ── a sub-item whose parent is not this reader's to see ────────────────────
@pytest.fixture
def behind_a_closed_parent(client, admin_id, guinea_id):
    """The permission model allows it: a sub-item carries its own overrides,
    so somebody can be let into a line of a work plan without being let into
    the plan."""
    bid = _board(client, admin_id, invite=[guinea_id])
    parent = _item(client, bid, admin_id, "תוכנית חסויה")
    kid = _item(client, bid, admin_id, "שורה סימן", parent=parent)
    other = _item(client, bid, admin_id, "שורה רגילה", parent=parent)
    r = client.post(f"/api/tasks/{parent}/permissions",
                    json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"},
                    headers=_h(admin_id))
    assert r.status_code == 200, r.text
    return {"bid": bid, "parent": parent, "kid": kid, "other": other,
            "owner": admin_id, "reader": guinea_id}


def test_the_match_is_not_lost_with_the_parent(client, behind_a_closed_parent):
    """Dropping the parent used to drop the sub-item with it — the row hangs
    under its parent — so a match this person is entitled to simply vanished."""
    b = behind_a_closed_parent
    r = _query(client, b["bid"], b["reader"], filter=_on("סימן"))
    rows = [i for i in r["items"] if i["id"] == b["parent"]]
    assert rows, "a sub-item they may read disappeared with its parent"
    assert [s["title"] for s in rows[0]["subtasks"]] == ["שורה סימן"]


def test_the_wrapper_discloses_nothing_about_the_parent(client, behind_a_closed_parent):
    """"ולא לחשוף את פרטי האב." The title above all — it is usually the whole
    of what a row discloses."""
    b = behind_a_closed_parent
    r = _query(client, b["bid"], b["reader"], filter=_on("סימן"))
    shell = next(i for i in r["items"] if i["id"] == b["parent"])
    assert shell["title"] == ""
    assert shell["status"] is None and shell["priority"] is None
    assert shell["custom_fields"] == {} and shell["assignees"] == []
    assert shell["due_date"] is None and shell["created_by"] is None
    blob = str(shell)
    assert "תוכנית חסויה" not in blob
    assert "שורה רגילה" not in blob, "a sub-item they cannot read came along"


def test_the_wrapper_says_what_it_is(client, behind_a_closed_parent):
    """Two different facts for the screen: "did not match" and "nothing here
    to show you" are drawn differently."""
    b = behind_a_closed_parent
    r = _query(client, b["bid"], b["reader"], filter=_on("סימן"))
    shell = next(i for i in r["items"] if i["id"] == b["parent"])
    assert shell["context_only"] is True and shell["restricted"] is True


def test_the_owner_sees_the_real_row_instead(client, behind_a_closed_parent):
    b = behind_a_closed_parent
    r = _query(client, b["bid"], b["owner"], filter=_on("סימן"))
    row = next(i for i in r["items"] if i["id"] == b["parent"])
    assert row["title"] == "תוכנית חסויה"
    assert row["restricted"] is False and row["context_only"] is True


def test_a_closed_parent_with_no_matching_child_stays_closed(client, behind_a_closed_parent):
    """The wrapper exists to carry matches. With none, there is nothing to
    carry and nothing to say."""
    b = behind_a_closed_parent
    r = _query(client, b["bid"], b["reader"], filter=_on("לא-קיים"))
    assert [i for i in r["items"] if i["id"] == b["parent"]] == []


# ── conditions are asked of the row itself ─────────────────────────────────
def test_a_sub_item_does_not_inherit_its_parents_values(client, admin_id):
    """"אין ירושה אוטומטית של ערך מהאב." A sub-item with nothing in the field
    does not answer for what its parent has in it."""
    bid = _board(client, admin_id)
    parent = _item(client, bid, admin_id, "הורה", priority="high")
    _item(client, bid, admin_id, "ילד", parent=parent)

    r = _query(client, bid, admin_id,
               filter={"op": "and", "rules": [{"field": "priority", "op": "eq", "v": "high"}]})
    row = next((i for i in r["items"] if i["id"] == parent), None)
    assert row is not None and row["context_only"] is False
    assert row["subtasks"] == [], "the child answered with its parent's priority"


def test_an_empty_value_means_on_a_sub_item_what_it_means_anywhere(client, admin_id):
    """"משמעות ערך ריק ואופרטורים מולו תישאר לפי מנגנון הסינון הקיים" — so
    the same operator, unchanged, decides it."""
    bid = _board(client, admin_id)
    parent = _item(client, bid, admin_id, "הורה", due_date="2026-03-03")
    _item(client, bid, admin_id, "ילד בלי תאריך", parent=parent)

    empty = _query(client, bid, admin_id,
                   filter={"op": "and", "rules": [{"field": "due", "op": "empty"}]})
    row = next((i for i in empty["items"] if i["id"] == parent), None)
    assert row is not None, "the child with no date did not bring its parent as context"
    assert [s["title"] for s in row["subtasks"]] == ["ילד בלי תאריך"]
    assert row["context_only"] is True, "the parent HAS a date and should not have matched"


def test_a_column_is_matched_by_id_and_not_by_its_title(client, admin_id):
    """"אין להתאים עמודות רק לפי שם תצוגה." Two columns can wear one title;
    a filter naming one of them must not answer for the other."""
    bid = _board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}",
                     json={"user_id": admin_id,
                           "columns": [{"type": "text", "title": "הערה"},
                                       {"type": "text", "title": "הערה"}]},
                     headers=_h(admin_id))
    assert r.status_code == 200, r.text
    first, second = [c["id"] for c in r.json()["columns"]][:2]
    assert first != second

    tid = _item(client, bid, admin_id, "פריט")
    client.patch(f"/api/tasks/{tid}",
                 json={"user_id": admin_id, "custom_fields": {first: "סימן"}},
                 headers=_h(admin_id))

    hit = _query(client, bid, admin_id,
                 filter={"op": "and", "rules": [{"field": first, "op": "has", "v": "סימן"}]})
    miss = _query(client, bid, admin_id,
                  filter={"op": "and", "rules": [{"field": second, "op": "has", "v": "סימן"}]})
    assert any(i["id"] == tid for i in hit["items"])
    assert not any(i["id"] == tid for i in miss["items"]), \
        "the other column with the same title answered"
