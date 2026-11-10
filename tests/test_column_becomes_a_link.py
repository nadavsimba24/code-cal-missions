"""המרת עמודה לעמודת "חיבור ללוח" — a column of words becomes a column of links.

A "לקוחות" column on a production board holds the names of customers as text,
typed by hand over two years. The records those names refer to live on another
board. Turning the one into the other is not a retype: a retype reads a cell
into words and writes those words back in another SHAPE, and there is no shape
that turns the word "עיריית חיפה" into a relationship. There is only a search
for a record that happens to be called that — and a search can fail.

The whole feature is the discipline around that failure, and that discipline is
what this file pins:

    a link is written only where exactly one visible, non-deleted record on the
    target board carries exactly that value. Everything else is an exception a
    person resolves by hand.

Which means, concretely, and each of these is a test below:

  · nothing is guessed. The one normalisation is trim / collapse internal
    whitespace / casefold, and there is deliberately nothing else — no
    punctuation stripping, no prefix match, no edit distance. A conversion that
    guesses produces output nobody can check, and being checkable is the entire
    value of the feature.
  · a cell is `matched` only when EVERY one of its words found exactly one
    record. Half-converting a dropdown that says two things would silently drop
    one of them and the cell would look finished.
  · the ways a cell can fail have a fixed precedence — no_match before partial
    before several before too_many_values — because "this customer is not on
    that board" is the thing the admin has to act on, and "the column only holds
    one" is a setting they can change.
  · no record is ever invented on the target board, by any path.
  · no original value is destroyed. Every non-empty cell is copied onto the
    conversion before the column changes under it, which is what lets
    "ביטול ההמרה" put the board back byte for byte — and it is why a MATCHED
    cell keeps a row too.
  · a record the actor cannot see is not a match and is not a candidate for an
    ambiguity either. It does not exist for this run. Letting it be either one
    would turn a conversion into a way of reading a board you were never
    invited to, which is the one failure here that is a security failure.
  · a matched record that is later deleted comes back onto the exception list
    as `target_deleted` and holds the conversion open, because a cell pointing
    at nothing is exactly the state a person has to be told about.
  · every one of the six endpoints is board admin on the source AND a member of
    the target. Two-way needs board ADMIN on the target as well, because a
    two-way column CREATES a column over there. A board the actor is not in
    refuses without naming it, and a column on the target they may not see is
    neither offered as a match field nor usable as one — and the refusal is
    the same 404 a column that does not exist gets, because "it is there but
    not for you" is itself the answer the oracle wanted.

Every test builds its own pair of boards and touches nothing it did not make,
so the suite stays idempotent against the shared seeded temp DB (invariant 15).
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"
HARNESS = ROOT / "tests" / "frontend" / "column_to_link_wizard.mjs"

AS = lambda uid: {"X-CityOS-User": str(uid)}          # noqa: E731
COUNTS = ("total", "empty", "matched", "unmatched", "ambiguous")


# ── building a board pair ───────────────────────────────────────────────────

def _board(client, admin_id, name):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, admin_id, bid, cols):
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": cols})
    assert r.status_code == 200, r.text
    return r.json()["columns"]


def _col(client, admin_id, bid, **col):
    return _cols(client, admin_id, bid, [col])[0]


def _item(client, admin_id, bid, title, cid=None, val=None):
    tid = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                          "user_id": admin_id}).json()["id"]
    if cid is not None:
        r = client.patch(f"/api/tasks/{tid}",
                         json={"user_id": admin_id, "custom_fields": {cid: val}})
        assert r.status_code == 200, r.text
    return tid


def _pair(client, admin_id, tag, titles, **source_col):
    """A source board carrying one column, and a target board of records.

    Returns (source_board, target_board, col_id, [record ids in the order the
    titles were given]). Both boards arrive with three demo items of their own,
    which is deliberate: the counts below have to survive a board that is not
    only the rows the test wrote.
    """
    source_col.setdefault("type", "text")
    source_col.setdefault("title", "לקוחות")
    a = _board(client, admin_id, f"מקור {tag}")
    b = _board(client, admin_id, f"לקוחות {tag}")
    cid = _col(client, admin_id, a, **source_col)["id"]
    return a, b, cid, [_item(client, admin_id, b, t) for t in titles]


# ── talking to the six endpoints ────────────────────────────────────────────

def _fields(client, bid, tbid, uid):
    return client.get(f"/api/boards/{bid}/link-match/fields?target_board_id={tbid}",
                      headers=AS(uid))


def _preview(client, bid, cid, tbid, uid, match_field="title", multiple=None,
             smart=None, fallback=None):
    """`multiple`, `smart` and the fallback field are all left off unless a
    test names them — each one changes the answer, so a test that does not
    send one is asserting about the server's own default for it."""
    url = (f"/api/boards/{bid}/columns/{cid}/link-match"
           f"?target_board_id={tbid}&match_field={match_field}")
    for key, val in (("multiple", multiple), ("smart", smart)):
        if val is not None:
            url += f"&{key}=" + ("true" if val else "false")
    if fallback is not None:
        url += f"&match_field_fallback={fallback}"
    return client.get(url, headers=AS(uid))


def _apply(client, bid, cid, tbid, uid, match_field="title", **body):
    return client.post(f"/api/boards/{bid}/columns/{cid}/link-match",
                       json={"target_board_id": tbid, "match_field": match_field, **body},
                       headers=AS(uid))


def _exceptions(client, bid, cid, uid, query=""):
    return client.get(f"/api/boards/{bid}/columns/{cid}/link-exceptions{query}",
                      headers=AS(uid))


def _resolve(client, bid, cid, task_id, uid, **body):
    return client.post(f"/api/boards/{bid}/columns/{cid}/link-exceptions/{task_id}",
                       json=body, headers=AS(uid))


def _revert(client, bid, cid, uid):
    return client.post(f"/api/boards/{bid}/columns/{cid}/link-revert",
                       json={}, headers=AS(uid))


# ── reading the board back ──────────────────────────────────────────────────

def _tasks(client, bid, uid):
    return {t["id"]: t for t in client.get(f"/api/boards/{bid}", headers=AS(uid)).json()["tasks"]}


def _coldef(client, bid, cid, uid):
    d = client.get(f"/api/boards/{bid}", headers=AS(uid)).json()
    return next(c for c in d["columns"] if c["id"] == cid)


def _cell(client, bid, cid, tid, uid):
    return (_tasks(client, bid, uid)[tid].get("custom_fields") or {}).get(cid)


def _counts(payload):
    return {k: payload[k] for k in COUNTS}


def _by_task(rows):
    return {r["task_id"]: r for r in rows}


def _record_ids(client, bid, uid):
    return sorted(_tasks(client, bid, uid))


def _board_name(client, bid, uid):
    return client.get(f"/api/boards/{bid}", headers=AS(uid)).json()["name"]


# ════════════════════════════════════════════════════════════════════════════
# the rule, one outcome at a time
# ════════════════════════════════════════════════════════════════════════════

def test_a_value_that_names_exactly_one_record_becomes_a_link_to_it(client, admin_id):
    """The happy path, and the only path on which anything is written at all."""
    a, b, cid, recs = _pair(client, admin_id, "m1", ["עיריית חיפה", "רשות העתיקות"])
    t = _item(client, admin_id, a, "פרויקט א m1", cid, "עיריית חיפה")

    p = _preview(client, a, cid, b, admin_id).json()
    assert (p["matched"], p["unmatched"], p["ambiguous"]) == (1, 0, 0)
    # the fields, not the whole dict: a sample row gained `tier`/`tier_he` when
    # the ladder landed, and a test that compares the shape rather than the
    # answer breaks every time the row learns to say one more thing
    s = p["samples"][0]
    assert len(p["samples"]) == 1
    assert (s["task_id"], s["item"], s["before"]) == (t, "פרויקט א m1", "עיריית חיפה")
    assert s["after"] == {"id": recs[0], "title": "עיריית חיפה"}
    # and it says which tier answered, which for an exact hit is the strict one
    assert s["tier"] == "exact"

    assert _apply(client, a, cid, b, admin_id).status_code == 200
    # by id, which is the whole point: the cell now holds the record, not a copy
    # of its name
    assert _cell(client, a, cid, t, admin_id) == [recs[0]]


def test_two_records_with_the_same_value_are_an_ambiguity_and_nothing_is_written(
        client, admin_id):
    """Collapsing to the first would be the guess this feature exists to refuse.
    Both candidates are carried so the person choosing can see what they are
    choosing between."""
    a, b, cid, recs = _pair(client, admin_id, "m2", ["מועצה", "מועצה"])
    t = _item(client, admin_id, a, "פרויקט ב m2", cid, "מועצה")

    p = _preview(client, a, cid, b, admin_id).json()
    assert (p["matched"], p["ambiguous"]) == (0, 1)
    exc = p["exceptions"][0]
    assert exc["outcome"] == "ambiguous" and exc["reason"] == "several"
    assert [c["id"] for c in exc["candidates"]] == recs

    assert _apply(client, a, cid, b, admin_id).status_code == 200
    assert not _cell(client, a, cid, t, admin_id), "a guess was written"
    assert _by_task(_exceptions(client, a, cid, admin_id).json()["rows"])[t]["reason"] \
        == "several"


def test_a_value_no_record_carries_is_left_for_a_person(client, admin_id):
    """Nothing is linked and the original words are still readable in the cell.

    This used to read "עיריה חיפה" against "עיריית חיפה" and call it no_match,
    which the ktiv tier now joins — that pair is one town spelled two ways.
    The half of the test that was never about spelling is the half that
    matters and is what it pins now: a value with no record behind it links
    NOTHING, and the cell goes on showing what it used to say.
    """
    a, b, cid, recs = _pair(client, admin_id, "m3", ["עיריית חיפה"])
    t = _item(client, admin_id, a, "פרויקט ג m3", cid, "קריית אונו")

    p = _preview(client, a, cid, b, admin_id).json()
    assert (p["matched"], p["unmatched"]) == (0, 1)
    assert p["exceptions"][0]["reason"] == "no_match"
    assert p["exceptions"][0]["candidates"] == []

    assert _apply(client, a, cid, b, admin_id).status_code == 200
    assert not _cell(client, a, cid, t, admin_id)
    # and the words are not lost — the cell says what it used to say
    assert _tasks(client, a, admin_id)[t]["link_pending"] == {cid: "קריית אונו"}


def test_an_empty_cell_is_not_an_exception_and_gets_no_row(client, admin_id):
    """There is nothing to keep and nothing to resolve. An empty column that
    counted every blank row as waiting for a person would be an exception list
    of four hundred rows nobody can work through."""
    a, b, cid, recs = _pair(client, admin_id, "m4", ["עיריית חיפה"])
    blank = _item(client, admin_id, a, "ריק m4", cid, "")
    none = _item(client, admin_id, a, "חסר m4")

    p = _preview(client, a, cid, b, admin_id).json()
    assert (p["matched"], p["unmatched"], p["ambiguous"]) == (0, 0, 0)
    assert p["empty"] == p["total"] and p["exceptions"] == []

    r = _apply(client, a, cid, b, admin_id)
    assert r.status_code == 200, r.text
    # no open row at all — the conversion opens with an empty list
    assert _exceptions(client, a, cid, admin_id).json()["total"] == 0
    for t in (blank, none):
        assert not _cell(client, a, cid, t, admin_id)
        assert "link_pending" not in _tasks(client, a, admin_id)[t]


def test_a_cell_with_more_values_than_a_single_link_column_can_hold_is_an_ambiguity(
        client, admin_id):
    """Both words found their record. The column can hold one of them, so a
    person picks — nothing is truncated behind their back."""
    a, b, cid, recs = _pair(client, admin_id, "m5", ["עיריית חיפה", "רשות העתיקות"],
                            type="dropdown", options=["עיריית חיפה", "רשות העתיקות"])
    t = _item(client, admin_id, a, "פרויקט ד m5", cid, ["עיריית חיפה", "רשות העתיקות"])

    p = _preview(client, a, cid, b, admin_id, multiple=False).json()
    assert (p["matched"], p["ambiguous"]) == (0, 1)
    exc = p["exceptions"][0]
    assert (exc["outcome"], exc["reason"]) == ("ambiguous", "too_many_values")
    assert [c["id"] for c in exc["candidates"]] == recs

    assert _apply(client, a, cid, b, admin_id, multiple=False).status_code == 200
    assert not _cell(client, a, cid, t, admin_id)


def test_a_cell_where_one_value_matches_and_another_misses_is_partial_not_no_match(
        client, admin_id):
    """`partial` is a reason of its own, and the distinction is the whole
    content of the exception row: "this cell found nothing" and "this cell found
    half of what it says" are different problems for whoever has to fix them.

    It is also the reason a cell is `matched` only when EVERY word matched —
    writing the half that worked would leave a cell that looks finished and has
    quietly lost a customer.
    """
    a, b, cid, recs = _pair(client, admin_id, "m6", ["עיריית חיפה"],
                            type="dropdown", options=["עיריית חיפה", "רשות העתיקות"])
    t = _item(client, admin_id, a, "פרויקט ה m6", cid, ["עיריית חיפה", "רשות העתיקות"])

    p = _preview(client, a, cid, b, admin_id).json()
    assert (p["matched"], p["unmatched"], p["ambiguous"]) == (0, 1, 0)
    exc = p["exceptions"][0]
    assert (exc["outcome"], exc["reason"]) == ("unmatched", "partial")
    assert exc["before"] == "עיריית חיפה, רשות העתיקות"

    assert _apply(client, a, cid, b, admin_id).status_code == 200
    assert not _cell(client, a, cid, t, admin_id), "the half that matched was written"
    row = _by_task(_exceptions(client, a, cid, admin_id).json()["rows"])[t]
    assert row["reason"] == "partial"
    # a partial cell HAS matched ids. Storing one as the link would claim a
    # relationship that was never written — and target_deleted reads that field
    # to decide a row needs re-pointing.
    assert row["linked_task_id"] is None


def test_the_order_in_which_a_cell_can_fail_is_fixed(client, admin_id):
    """no_match → partial → several → too_many_values, first match wins.

    Six cells, one preview, the whole table. The precedence is not arbitrary: a
    value that exists nowhere on the target board is reported before a
    cardinality complaint, because the first is work on the data and the second
    is a switch in the dialog.
    """
    a, b, cid, recs = _pair(
        client, admin_id, "m7", ["עיריית חיפה", "רשות העתיקות", "מועצה", "מועצה"],
        type="dropdown",
        options=["עיריית חיפה", "רשות העתיקות", "מועצה", "אין כזה"])
    cells = {
        "no_match":        ["אין כזה"],
        "partial":         ["עיריית חיפה", "אין כזה"],
        "several":         ["מועצה"],
        "too_many_values": ["עיריית חיפה", "רשות העתיקות"],
        # a missing word and an ambiguous word together: no_match wins, and the
        # row reports `partial` because something else in the cell did match
        "partial beats several": ["מועצה", "אין כזה"],
        # an ambiguous word in a cell too long for a single-link column:
        # `several` wins
        "several beats too_many": ["מועצה", "עיריית חיפה"],
    }
    ids = {name: _item(client, admin_id, a, name + " m7", cid, val)
           for name, val in cells.items()}

    p = _preview(client, a, cid, b, admin_id, multiple=False).json()
    got = {name: (r["outcome"], r["reason"])
           for name, tid in ids.items()
           for r in [_by_task(p["exceptions"]).get(tid)] if r}
    assert got == {
        "no_match":                ("unmatched", "no_match"),
        "partial":                 ("unmatched", "partial"),
        "several":                 ("ambiguous", "several"),
        "too_many_values":         ("ambiguous", "too_many_values"),
        "partial beats several":   ("unmatched", "partial"),
        "several beats too_many":  ("ambiguous", "several"),
    }, got
    # a partial cell carries no candidates: the words it DID match are not
    # answers to the question the row is asking
    assert _by_task(p["exceptions"])[ids["partial beats several"]]["candidates"] == []
    assert (p["matched"], p["unmatched"], p["ambiguous"]) == (0, 3, 3)


def test_the_tiers_that_link_by_themselves_join_spellings_and_nothing_else(
        client, admin_id):
    """What tier 0 and tier 1 promise, now that they are not the only tiers.

    This test used to be called "whitespace and case are the only things
    normalised" and it was right until the user ran the conversion against her
    own board: 474 of 476 cells came back unmatched, every one of them a match
    a person reads instantly. She asked for containment and acronyms, and the
    strict rule stopped being the whole answer.

    What it did NOT stop being is the whole answer for the tiers that link
    WITHOUT asking. Tier 1 joins `קק״ל` to `קקל` and `עיריית חיפה.` to
    `עיריית חיפה` because those are one string spelled two ways — the same
    letters in the same order, the same words in the same places. The moment a
    tier changes WHICH words are compared it stops linking and starts
    proposing, and that boundary is the whole safety of the ladder.

    So what is pinned here is the boundary, not the strictness: punctuation
    and ktiv variants link, a prefix and a welded-together word do not.
    """
    a, b, cid, recs = _pair(client, admin_id, "m8",
                            ["עיריית חיפה", "Haifa Municipality"])
    # one string, spelled differently — linked, no question asked
    spellings = {
        "לפני ואחרי":  "  עיריית חיפה  ",
        "באמצע":       "עיריית   חיפה",
        "אותיות":      "haifa MUNICIPALITY",
        "נקודה":       "עיריית חיפה.",
        "גרשיים":      'עיריית "חיפה"',
        "כתיב חסר":    "עירית חיפה",
    }
    # a different claim about the world — never linked by itself
    not_spellings = {
        "תחילית":   "עיריית",          # a descriptor and nothing else
        "אחר":      "עיריית חדרה",
    }
    ids = {k: _item(client, admin_id, a, k + " m8", cid, v)
           for k, v in list(spellings.items()) + list(not_spellings.items())}

    p = _preview(client, a, cid, b, admin_id).json()
    linked = {r["task_id"] for r in p["samples"]}
    assert p["matched"] == len(spellings), p
    assert linked == {ids[k] for k in spellings}, \
        [r["before"] for r in p["samples"]]
    # every one of them on a tier that links by itself, and no looser one
    assert {r["tier"] for r in p["samples"]} <= {"exact", "punct"}, p["samples"]

    # and the two that are not spellings linked nothing — whatever else became
    # of them, neither is in the matched set
    for k in not_spellings:
        assert ids[k] not in linked, k
    assert p["suggested"] + p["unmatched"] + p["ambiguous"] == len(not_spellings)


def test_a_word_welded_together_is_proposed_and_never_linked(client, admin_id):
    """Dropping the word boundaries is the one normalisation that can weld two
    different names into one string, so it is the one tier-1 refuses to do by
    itself. "עירייתחיפה" is probably "עיריית חיפה" and probably is not good
    enough to write."""
    a, b, cid, recs = _pair(client, admin_id, "m9", ["עיריית חיפה"])
    t = _item(client, admin_id, a, "בלי רווח m9", cid, "עירייתחיפה")

    p = _preview(client, a, cid, b, admin_id).json()
    assert p["matched"] == 0, p
    assert p["suggested"] == 1
    sug = p["suggestions"][0]
    assert sug["task_id"] == t and sug["tier"] == "spelling"
    assert [c["id"] for c in sug["candidates"]] == [recs[0]]

    # and applying without accepting it writes nothing
    assert _apply(client, a, cid, b, admin_id).status_code == 200
    assert not _cell(client, a, cid, t, admin_id)



# ════════════════════════════════════════════════════════════════════════════
# the field a record is identified by
# ════════════════════════════════════════════════════════════════════════════

def test_the_match_field_can_be_a_column_of_the_target_board(client, admin_id):
    """A customer is more reliably found by ח.פ. than by a name somebody typed.

    The key is the column id VERBATIM — not "col_" + id — so the value the
    fields endpoint hands out is the value the preview takes back.
    """
    a = _board(client, admin_id, "מקור f1")
    b = _board(client, admin_id, "לקוחות f1")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    hp = _col(client, admin_id, b, type="text", title="ח.פ.")["id"]
    rec = _item(client, admin_id, b, "עיריית חיפה f1", hp, "500100200")
    t = _item(client, admin_id, a, "פרויקט f1", cid, "500100200")

    keys = [f["key"] for f in _fields(client, a, b, admin_id).json()["fields"]]
    assert hp in keys, keys
    assert not any(k.startswith("col_col_") for k in keys), keys

    p = _preview(client, a, cid, b, admin_id, match_field=hp).json()
    assert (p["matched"], p["match_field"]) == (1, hp)
    r = _apply(client, a, cid, b, admin_id, match_field=hp)
    assert r.status_code == 200, r.text
    assert _cell(client, a, cid, t, admin_id) == [rec]
    # the column remembers what it was matched by, so the exception list and the
    # connect config can go on saying it
    assert _coldef(client, a, cid, admin_id)["connect"]["match_field"] == hp


def test_a_field_that_cannot_identify_a_record_is_refused(client, admin_id):
    """A date or a person is not an identity: two items sharing an owner are not
    the same customer, and offering it would mostly produce ambiguity."""
    a = _board(client, admin_id, "מקור f2")
    b = _board(client, admin_id, "לקוחות f2")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    when = _col(client, admin_id, b, type="date", title="מועד")["id"]
    _item(client, admin_id, a, "פרויקט f2", cid, "משהו")

    assert when not in [f["key"] for f in _fields(client, a, b, admin_id).json()["fields"]]
    bad = _preview(client, a, cid, b, admin_id, match_field=when)
    assert bad.status_code == 400, bad.text
    gone = _preview(client, a, cid, b, admin_id, match_field="col_nothing")
    assert gone.status_code == 404, gone.text


def test_the_fields_list_counts_the_values_that_repeat(client, admin_id):
    """`duplicates` is the number that decides the choice, and it is said BEFORE
    the admin picks the field rather than after they have run the conversion and
    got an ambiguity list instead."""
    a = _board(client, admin_id, "מקור f3")
    b = _board(client, admin_id, "לקוחות f3")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    # the target board arrives with three demo items of its own; this test is
    # about its own records, so they go
    for tid in _record_ids(client, b, admin_id):
        assert client.delete(f"/api/tasks/{tid}?user_id={admin_id}").status_code == 200
    for t in ("עיריית חיפה", "מועצה", "מועצה", "רשות העתיקות"):
        _item(client, admin_id, b, t)

    d = _fields(client, a, b, admin_id).json()
    assert d["records"] == 4 and d["target_board_name"] == "לקוחות f3"
    title = next(f for f in d["fields"] if f["key"] == "title")
    assert title["label"] == "שם הפריט" and title["type"] == "title"
    assert (title["filled"], title["distinct"], title["duplicates"]) == (4, 3, 1)


# ════════════════════════════════════════════════════════════════════════════
# the preview is what the apply does
# ════════════════════════════════════════════════════════════════════════════

def test_the_preview_counts_are_what_applying_actually_does(client, admin_id):
    """The preview is the thing somebody agrees to. A plan that disagreed with
    the write would make the agreement worthless — so the apply re-runs the same
    plan on the server rather than trusting the counts a client posts."""
    a, b, cid, recs = _pair(client, admin_id, "p1", ["עיריית חיפה", "מועצה", "מועצה"],
                            type="dropdown",
                            options=["עיריית חיפה", "מועצה", "אין כזה"])
    good = _item(client, admin_id, a, "מותאם p1", cid, ["עיריית חיפה"])
    miss = _item(client, admin_id, a, "חסר p1", cid, ["אין כזה"])
    dupe = _item(client, admin_id, a, "כפול p1", cid, ["מועצה"])
    _item(client, admin_id, a, "ריק p1", cid, [])

    p = _preview(client, a, cid, b, admin_id).json()
    r = _apply(client, a, cid, b, admin_id)
    assert r.status_code == 200, r.text
    assert _counts(r.json()) == _counts(p), (r.json(), p)
    assert (p["matched"], p["unmatched"], p["ambiguous"]) == (1, 1, 1)

    # and the counts describe the board, not just each other
    cells = _tasks(client, a, admin_id)
    linked = [t for t in cells.values() if (t.get("custom_fields") or {}).get(cid)]
    assert [t["id"] for t in linked] == [good]
    e = _exceptions(client, a, cid, admin_id).json()
    assert e["open"] == p["unmatched"] + p["ambiguous"] == 2
    assert sorted(_by_task(e["rows"])) == sorted([miss, dupe])


def test_the_preview_counts_single_link_overflow_only_when_told_the_column_is_single(
        client, admin_id):
    """`multiple` is a query parameter on the preview and it is not optional in
    practice: omit it and too_many_values counts as zero, so the wizard's step
    two would promise a conversion its own step three does not perform. The
    single/multi switch has to feed this call.
    """
    a, b, cid, recs = _pair(client, admin_id, "p2", ["עיריית חיפה", "רשות העתיקות"],
                            type="dropdown",
                            options=["עיריית חיפה", "רשות העתיקות"])
    t = _item(client, admin_id, a, "שניים p2", cid, ["עיריית חיפה", "רשות העתיקות"])

    multi = _preview(client, a, cid, b, admin_id, multiple=True).json()
    single = _preview(client, a, cid, b, admin_id, multiple=False).json()
    default = _preview(client, a, cid, b, admin_id).json()

    assert (multi["matched"], multi["ambiguous"]) == (1, 0)
    assert (single["matched"], single["ambiguous"]) == (0, 1)
    assert default["multiple"] is True and _counts(default) == _counts(multi)

    # the equality that matters: with multiple=false, the preview and the apply
    # agree. This is the pairing a forgotten parameter silently breaks.
    done = _apply(client, a, cid, b, admin_id, multiple=False)
    assert done.status_code == 200, done.text
    assert _counts(done.json()) == _counts(single), (done.json(), single)
    assert not _cell(client, a, cid, t, admin_id)


def test_the_items_in_the_recycle_bin_are_counted_and_converted_too(client, admin_id):
    """A cell left holding the old type's value is a wrong cell the day somebody
    restores the item, and a restore is the worst place to discover it."""
    a, b, cid, recs = _pair(client, admin_id, "p3", ["עיריית חיפה"])
    live = _item(client, admin_id, a, "חי p3", cid, "עיריית חיפה")
    binned = _item(client, admin_id, a, "בסל p3", cid, "עיריית חיפה")
    assert client.delete(f"/api/tasks/{binned}?user_id={admin_id}").status_code == 200

    p = _preview(client, a, cid, b, admin_id).json()
    assert p["matched"] == 2, p
    assert _apply(client, a, cid, b, admin_id).json()["matched"] == 2
    assert _cell(client, a, cid, live, admin_id) == [recs[0]]
    restored = client.post(f"/api/tasks/{binned}/restore", json={"user_id": admin_id})
    assert restored.status_code == 200, restored.text
    assert _cell(client, a, cid, binned, admin_id) == [recs[0]]


# ════════════════════════════════════════════════════════════════════════════
# what the apply writes, and what it refuses to
# ════════════════════════════════════════════════════════════════════════════

def test_no_record_is_ever_created_on_the_target_board(client, admin_id):
    """Not by the preview, not by the apply, not by resolving an exception, not
    by a revert. A conversion that invented the customers it could not find
    would be a conversion nobody could undo."""
    a, b, cid, recs = _pair(client, admin_id, "w1", ["עיריית חיפה"])
    _item(client, admin_id, a, "מותאם w1", cid, "עיריית חיפה")
    t = _item(client, admin_id, a, "חסר w1", cid, "אין כזה")
    before = _record_ids(client, b, admin_id)

    _preview(client, a, cid, b, admin_id)
    assert _record_ids(client, b, admin_id) == before, "the preview wrote to the board"
    assert _apply(client, a, cid, b, admin_id).status_code == 200
    assert _record_ids(client, b, admin_id) == before, "the apply invented a record"
    assert _resolve(client, a, cid, t, admin_id, item_id=recs[0]).status_code == 200
    assert _record_ids(client, b, admin_id) == before
    _revert(client, a, cid, admin_id)
    assert _record_ids(client, b, admin_id) == before


def test_a_two_way_conversion_writes_the_mirror_both_ways(client, admin_id):
    """Through the existing write path in both directions. A conversion that
    inserted its own ItemLink row would be a second implementation of the rule
    that keeps the two sides in step."""
    a, b, cid, recs = _pair(client, admin_id, "w2", ["עיריית חיפה"])
    t = _item(client, admin_id, a, "פרויקט w2", cid, "עיריית חיפה")

    r = _apply(client, a, cid, b, admin_id, two_way=True)
    assert r.status_code == 200, r.text
    col = _coldef(client, a, cid, admin_id)
    assert col["connect"]["two_way"] is True
    mirror = col["connect"]["mirror"][str(b)]
    assert _cell(client, a, cid, t, admin_id) == [recs[0]]
    # the other end of the relationship exists, on a column that appeared on the
    # target board
    assert mirror in [c["id"] for c in client.get(f"/api/boards/{b}",
                                                  headers=AS(admin_id)).json()["columns"]]
    assert _cell(client, b, mirror, recs[0], admin_id) == [t]


def test_the_column_is_rebuilt_as_a_link_and_keeps_nothing_of_the_old_type(
        client, admin_id):
    """A dropdown's options under a connect column are a vocabulary nothing
    reads, and the day somebody retypes it back they would reappear from
    nowhere. The old shape is cleared, and the conversion is where it survives.
    """
    a, b, cid, recs = _pair(client, admin_id, "w3", ["עיריית חיפה"],
                            type="dropdown", options=["עיריית חיפה", "אחר"])
    _item(client, admin_id, a, "פרויקט w3", cid, ["עיריית חיפה"])
    assert _apply(client, a, cid, b, admin_id).status_code == 200

    col = _coldef(client, a, cid, admin_id)
    assert col["type"] == "connect" and col["options"] is None
    assert col["connect"]["board_ids"] == [b]
    assert col["connect"]["multiple"] is True and col["connect"]["match_field"] == "title"


def test_a_column_can_hold_only_one_open_conversion_at_a_time(client, admin_id):
    """Two overlapping conversions would each hold a copy of "the original" and
    neither would be right."""
    a, b, cid, recs = _pair(client, admin_id, "w4", ["עיריית חיפה"])
    _item(client, admin_id, a, "חסר w4", cid, "אין כזה")
    assert _apply(client, a, cid, b, admin_id).status_code == 200
    again = _apply(client, a, cid, b, admin_id)
    assert again.status_code == 400, again.text
    assert "המרה פתוחה" in again.json()["detail"]


def test_a_form_asking_about_the_column_has_to_be_agreed_to(client, admin_id):
    """The same bargain the board PATCH and the retype strike, in the same 409
    shape — the browser has one handler for all three."""
    a, b, cid, recs = _pair(client, admin_id, "w5", ["עיריית חיפה"])
    _item(client, admin_id, a, "פרויקט w5", cid, "עיריית חיפה")
    me = AS(admin_id)
    fid = client.post(f"/api/boards/{a}/forms", json={}, headers=me).json()["id"]
    assert client.post(f"/api/forms/{fid}/components",
                       json={"kind": "question", "field_key": cid, "label": "לקוחות"},
                       headers=me).status_code == 200
    assert client.patch(f"/api/forms/{fid}", json={"status": "PUBLISHED"},
                        headers=me).status_code == 200

    r = _apply(client, a, cid, b, admin_id)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert [c["col_id"] for c in d["columns"]] == [cid]
    assert d["columns"][0]["new_type"] == "connect"
    assert d["columns"][0]["removed"] is False and d["columns"][0]["forms"]
    # refused means refused
    assert _coldef(client, a, cid, admin_id)["type"] == "text"

    ok = _apply(client, a, cid, b, admin_id, confirm_columns=[cid])
    assert ok.status_code == 200, ok.text
    assert _coldef(client, a, cid, admin_id)["type"] == "connect"


def test_the_board_log_says_the_column_became_a_link_to_that_board(client, admin_id):
    """"עמודה נמחקה" about a column still on the board is the one kind of log
    line nobody can check."""
    a, b, cid, recs = _pair(client, admin_id, "w6", ["עיריית חיפה"])
    _item(client, admin_id, a, "מותאם w6", cid, "עיריית חיפה")
    _item(client, admin_id, a, "חסר w6", cid, "אין כזה")
    assert _apply(client, a, cid, b, admin_id).status_code == 200

    rows = client.get(f"/api/boards/{a}/activity", headers=AS(admin_id)).json()["activity"]
    line = next(r for r in rows if r["field"] == "column" and r["action"] == "update")
    assert line["old"] == "לקוחות"
    # the board it now links to is named, not numbered — a line saying "לוח 9"
    # is a line written for whoever wrote the code
    assert "'לקוחות w6'" in line["new"], line["new"]
    assert str(b) not in line["new"], line["new"]
    assert "1 הותאמו" in line["new"] and "1 ממתינים" in line["new"], line["new"]


# ════════════════════════════════════════════════════════════════════════════
# the originals, and the undo they buy
# ════════════════════════════════════════════════════════════════════════════

def test_the_originals_survive_and_a_revert_puts_the_board_back_exactly(
        client, admin_id):
    """This is what "שמור את הערכים המקוריים עד להשלמת הטיפול" buys, and it is
    why a MATCHED cell keeps a conversion row too: a revert that restored only
    the cells it failed on would leave the matched ones as links and the board
    would be neither converted nor not.

    Byte for byte, including the whitespace somebody's paste left behind — a
    value a person has to recognise twice is a value that did not survive.
    """
    a, b, cid, recs = _pair(client, admin_id, "r1", ["עיריית חיפה", "מועצה", "מועצה"],
                            type="dropdown",
                            options=["עיריית חיפה", "מועצה", "אין כזה"])
    values = {
        "מותאם": ["  עיריית   חיפה "],
        "חסר":   ["אין כזה"],
        "כפול":  ["מועצה"],
        "ריק":   [],
    }
    ids = {k: _item(client, admin_id, a, k, cid, v) for k, v in values.items()}
    before_cols = client.get(f"/api/boards/{a}", headers=AS(admin_id)).json()["columns"]
    before_cells = {t["id"]: (t.get("custom_fields") or {}).get(cid)
                    for t in _tasks(client, a, admin_id).values()}

    assert _apply(client, a, cid, b, admin_id).json()["matched"] == 1
    assert _cell(client, a, cid, ids["מותאם"], admin_id) == [recs[0]]

    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "reverted"
    assert r.json()["restored"] == 3, "an empty cell was given a row to restore"

    after_cells = {t["id"]: (t.get("custom_fields") or {}).get(cid)
                   for t in _tasks(client, a, admin_id).values()}
    # Every cell that said anything says exactly the same thing again, down to
    # the whitespace. The empty one is compared as "still empty" rather than
    # identically: a dropdown cell stored as [] comes back absent, because the
    # revert has no conversion row for an empty cell and clears whatever the
    # column holds. Both are the same empty cell to _cell_words and to the
    # grid, but it is a deviation from "byte for byte" and it is reported.
    norm = lambda m: {k: (None if v in (None, [], "") else v) for k, v in m.items()}  # noqa: E731
    assert norm(after_cells) == norm(before_cells), \
        "the values did not come back as they were"
    assert after_cells[ids["מותאם"]] == ["  עיריית   חיפה "]
    assert after_cells[ids["חסר"]] == ["אין כזה"]
    assert after_cells[ids["כפול"]] == ["מועצה"]
    after_cols = client.get(f"/api/boards/{a}", headers=AS(admin_id)).json()["columns"]
    assert after_cols == before_cols, "the column definition did not come back"
    assert _coldef(client, a, cid, admin_id)["options"] == ["עיריית חיפה", "מועצה", "אין כזה"]
    # and the conversion is finished: there is nothing left to undo
    assert _exceptions(client, a, cid, admin_id).status_code == 404


def test_a_revert_after_the_conversion_closed_is_refused(client, admin_id):
    """Once the last exception has been dealt with the originals are history
    rather than a pending state, and undoing would overwrite links somebody has
    since chosen by hand."""
    a, b, cid, recs = _pair(client, admin_id, "r2", ["עיריית חיפה"])
    t = _item(client, admin_id, a, "חסר r2", cid, "אין כזה")
    assert _apply(client, a, cid, b, admin_id).status_code == 200
    assert _resolve(client, a, cid, t, admin_id, action="clear").json()["closed"] is True

    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "ההמרה הושלמה — אי אפשר לבטל אותה"


def test_a_revert_where_there_was_never_a_conversion_is_a_404(client, admin_id):
    a, b, cid, recs = _pair(client, admin_id, "r3", ["עיריית חיפה"])
    assert _revert(client, a, cid, admin_id).status_code == 404
    assert _exceptions(client, a, cid, admin_id).status_code == 404


# ════════════════════════════════════════════════════════════════════════════
# resolving what nobody could match
# ════════════════════════════════════════════════════════════════════════════

def test_an_exception_resolved_with_a_record_becomes_a_link(client, admin_id):
    a, b, cid, recs = _pair(client, admin_id, "x1", ["מועצה", "מועצה"])
    t = _item(client, admin_id, a, "פרויקט x1", cid, "מועצה")
    assert _apply(client, a, cid, b, admin_id).status_code == 200

    r = _resolve(client, a, cid, t, admin_id, item_id=recs[1])
    assert r.status_code == 200, r.text
    assert r.json() == {"open": 0, "resolved": 1, "total": 1, "closed": True}
    assert _cell(client, a, cid, t, admin_id) == [recs[1]]
    # and the cell stops saying it is waiting
    assert "link_pending" not in _tasks(client, a, admin_id)[t]


def test_an_exception_marked_unmatched_is_resolved_rather_than_deleted(client, admin_id):
    """"סמן כלא מותאם" is a decision, not a deletion — it says this value has
    no record behind it, and the words it used to hold are still on the
    conversion row.

    It was labelled "השאר ריק", which the action does not do: it answers the
    ROW, not the cell, so a link somebody made by hand survives it (see
    test_marking_a_row_unmatched_keeps_a_link_somebody_made_by_hand)."""
    a, b, cid, recs = _pair(client, admin_id, "x2", ["עיריית חיפה"])
    stay = _item(client, admin_id, a, "נשאר ריק x2", cid, "אין כזה")
    other = _item(client, admin_id, a, "עוד חסר x2", cid, "גם אין")
    assert _apply(client, a, cid, b, admin_id).status_code == 200

    r = _resolve(client, a, cid, stay, admin_id, action="clear")
    assert r.status_code == 200, r.text
    assert r.json() == {"open": 1, "resolved": 1, "total": 2, "closed": False}
    assert not _cell(client, a, cid, stay, admin_id)
    assert "link_pending" not in _tasks(client, a, admin_id)[stay]
    assert list(_by_task(_exceptions(client, a, cid, admin_id).json()["rows"])) == [other]
    # the originals are still there, which is why the revert below works
    rv = _revert(client, a, cid, admin_id)
    assert rv.status_code == 200 and rv.json()["restored"] == 2
    assert _cell(client, a, cid, stay, admin_id) == "אין כזה"


def test_the_last_resolution_closes_the_conversion(client, admin_id):
    a, b, cid, recs = _pair(client, admin_id, "x3", ["עיריית חיפה"])
    one = _item(client, admin_id, a, "אחד x3", cid, "אין כזה")
    two = _item(client, admin_id, a, "שניים x3", cid, "גם אין")
    assert _apply(client, a, cid, b, admin_id).status_code == 200

    assert _resolve(client, a, cid, one, admin_id, action="clear").json()["closed"] is False
    last = _resolve(client, a, cid, two, admin_id, item_id=recs[0])
    assert last.json() == {"open": 0, "resolved": 2, "total": 2, "closed": True}
    # closed means the exception list is gone and the board stops showing a count
    assert _exceptions(client, a, cid, admin_id).status_code == 404
    assert "conversion" not in _coldef(client, a, cid, admin_id)


def test_a_record_that_is_not_a_live_record_of_the_target_board_cannot_resolve(
        client, admin_id):
    """Every way of answering the question wrongly, and each is a 400 rather
    than a link to something the column was never pointed at."""
    a, b, cid, recs = _pair(client, admin_id, "x4", ["עיריית חיפה"])
    elsewhere = _board(client, admin_id, "לוח אחר x4")
    stranger = _item(client, admin_id, elsewhere, "זר x4")
    dead = _item(client, admin_id, b, "נמחק x4")
    # a sub-item of a record is not itself a record somebody links a customer
    # to, and _link_match_records never offered it as a match either
    sub = client.post("/api/tasks", json={"board_id": b, "title": "תת x4",
                                          "parent_id": recs[0],
                                          "user_id": admin_id}).json()["id"]
    assert client.delete(f"/api/tasks/{dead}?user_id={admin_id}").status_code == 200
    t = _item(client, admin_id, a, "פרויקט x4", cid, "אין כזה")
    assert _apply(client, a, cid, b, admin_id).status_code == 200

    for body in ({"item_id": stranger}, {"item_id": dead}, {"item_id": sub},
                 {"item_id": "לא מספר"}, {"item_id": 10 ** 9},
                 {}, {"action": "restore_text"}):
        r = _resolve(client, a, cid, t, admin_id, **body)
        assert r.status_code == 400, (body, r.status_code, r.text)
        assert isinstance(r.json()["detail"], str)
    # refused all the way through: the row is still open and still unlinked
    assert _exceptions(client, a, cid, admin_id).json()["open"] == 1
    assert not _cell(client, a, cid, t, admin_id)


def test_an_item_the_conversion_never_held_a_value_for_cannot_be_resolved(
        client, admin_id):
    """An empty cell got no conversion row — there was nothing to keep and
    nothing to resolve — so there is no exception to answer for it, and the
    resolver says so rather than inventing one."""
    a, b, cid, recs = _pair(client, admin_id, "x5", ["עיריית חיפה"])
    blank = _item(client, admin_id, a, "ריק x5", cid, "")
    _item(client, admin_id, a, "חסר x5", cid, "אין כזה")
    assert _apply(client, a, cid, b, admin_id).status_code == 200

    r = _resolve(client, a, cid, blank, admin_id, item_id=recs[0])
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "אין חריגה פתוחה לפריט זה"
    assert not _cell(client, a, cid, blank, admin_id)
    # and an item that is not on this board at all
    outside = _item(client, admin_id, b, "לא כאן x5")
    assert _resolve(client, a, cid, outside, admin_id,
                    item_id=recs[0]).status_code == 404


# ════════════════════════════════════════════════════════════════════════════
# a linked record that changes under the column
# ════════════════════════════════════════════════════════════════════════════

def test_a_linked_record_renamed_afterwards_shows_its_new_name(client, admin_id):
    """The link is by id. A renamed record showing its new name is not a
    special case to build, it is the reason for linking in the first place."""
    a, b, cid, recs = _pair(client, admin_id, "d1", ["עיריית חיפה"])
    t = _item(client, admin_id, a, "פרויקט d1", cid, "עיריית חיפה")
    assert _apply(client, a, cid, b, admin_id).status_code == 200

    assert client.patch(f"/api/tasks/{recs[0]}",
                        json={"user_id": admin_id, "title": "עיריית חיפה — אגף תשתיות"}
                        ).status_code == 200
    assert _cell(client, a, cid, t, admin_id) == [recs[0]], "the cell chased the rename"
    got = client.get(f"/api/tasks/lookup?ids={recs[0]}", headers=AS(admin_id)).json()
    assert got["items"][0]["title"] == "עיריית חיפה — אגף תשתיות"


def test_a_linked_record_deleted_afterwards_comes_back_as_an_exception(
        client, admin_id):
    """The one state a conversion cannot be allowed to close on: a cell pointing
    at nothing. It is listed again with reason `target_deleted`, it carries the
    dead id so the resolver can say what it used to be, and it counts toward
    `open` — so the conversion stays open until somebody re-points it.
    """
    a, b, cid, recs = _pair(client, admin_id, "d2", ["עיריית חיפה", "רשות העתיקות"])
    t = _item(client, admin_id, a, "פרויקט d2", cid, "עיריית חיפה")
    assert _apply(client, a, cid, b, admin_id).json()["matched"] == 1
    # everything matched, so there is nothing waiting — until the record goes
    assert _exceptions(client, a, cid, admin_id).json()["open"] == 0

    assert client.delete(f"/api/tasks/{recs[0]}?user_id={admin_id}").status_code == 200
    e = _exceptions(client, a, cid, admin_id).json()
    assert e["open"] == 1 and e["total"] == 1
    row = e["rows"][0]
    assert row["task_id"] == t
    assert (row["outcome"], row["reason"]) == ("unmatched", "target_deleted")
    assert row["linked_task_id"] == recs[0]
    assert row["before"] == "עיריית חיפה"
    # and the board says the conversion is still open, with one waiting
    assert _coldef(client, a, cid, admin_id)["conversion"]["open"] == 1

    done = _resolve(client, a, cid, t, admin_id, item_id=recs[1])
    assert done.status_code == 200, done.text
    assert done.json()["closed"] is True
    assert _cell(client, a, cid, t, admin_id) == [recs[1]]


def test_deleting_the_column_closes_its_conversion(client, admin_id):
    """Left open it would keep an exception list alive for a column nobody can
    see, and the count would ride on the board payload forever."""
    a, b, cid, recs = _pair(client, admin_id, "d3", ["עיריית חיפה"])
    _item(client, admin_id, a, "חסר d3", cid, "אין כזה")
    assert _apply(client, a, cid, b, admin_id).status_code == 200
    assert _exceptions(client, a, cid, admin_id).json()["open"] == 1

    assert client.patch(f"/api/boards/{a}",
                        json={"user_id": admin_id, "columns": []}).status_code == 200
    assert _exceptions(client, a, cid, admin_id).status_code == 404
    # closed, not orphaned: a revert answers "it is finished" rather than
    # "there was never one", which is the difference between the two states
    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "ההמרה הושלמה — אי אפשר לבטל אותה"


# ════════════════════════════════════════════════════════════════════════════
# who may run it, and what they are allowed to see while they do
# ════════════════════════════════════════════════════════════════════════════

def test_a_non_admin_is_refused_by_every_one_of_the_six_endpoints(
        client, admin_id, member_id):
    """An editor may fill a column in and may not change what it is. Six routes,
    six refusals — a family where one of them answers is a family with a hole in
    it, and the hole is whichever one nobody checked."""
    a, b, cid, recs = _pair(client, admin_id, "z1", ["עיריית חיפה"])
    for bid in (a, b):
        assert client.post(f"/api/boards/{bid}/members",
                           json={"actor_id": admin_id, "user_id": member_id,
                                 "role": "editor"}).status_code == 200
    t = _item(client, admin_id, a, "פרויקט z1", cid, "אין כזה")

    calls = [
        _fields(client, a, b, member_id),
        _preview(client, a, cid, b, member_id),
        _apply(client, a, cid, b, member_id),
        _exceptions(client, a, cid, member_id),
        _resolve(client, a, cid, t, member_id, action="clear"),
        _revert(client, a, cid, member_id),
    ]
    assert [r.status_code for r in calls] == [403] * 6, [r.status_code for r in calls]
    for r in calls:
        assert r.json()["detail"] == "רק מנהל הלוח יכול לערוך עמודות"
    # nothing of the refusal leaked into the board
    assert _coldef(client, a, cid, admin_id)["type"] == "text"


def test_a_target_board_the_actor_is_not_in_is_refused(client, admin_id, guinea_id):
    """The preview and the exception list quote the titles of records on the
    target board. A conversion must not be a way of reading a board you were
    never invited to."""
    a, b, cid, recs = _pair(client, admin_id, "z2", ["עיריית חיפה"])
    assert client.post(f"/api/boards/{a}/members",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "role": "admin"}).status_code == 200
    _item(client, admin_id, a, "פרויקט z2", cid, "עיריית חיפה")

    for r in (_fields(client, a, b, guinea_id),
              _preview(client, a, cid, b, guinea_id),
              _apply(client, a, cid, b, guinea_id)):
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == "אין לך גישה ללוח היעד"
    assert _coldef(client, a, cid, admin_id)["type"] == "text"


def test_a_record_the_actor_cannot_see_is_neither_a_match_nor_a_candidate(
        client, admin_id, guinea_id):
    """The permission leak this feature could most easily have been.

    An invisible record must not produce a match — that would hand somebody a
    link to a record they are not allowed to open — and it must not produce an
    AMBIGUITY either, which is the subtler half: "two records answer to this
    name" tells you a record exists that you cannot see. It does not exist for
    this run, so a name that two records carry and the actor can see one of is
    an ordinary unique match.
    """
    a, b, cid, recs = _pair(client, admin_id, "z3",
                            ["עיריית חיפה", "מועצה", "מועצה"])
    assert client.post(f"/api/boards/{a}/members",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "role": "admin"}).status_code == 200
    assert client.post(f"/api/boards/{b}/members",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "role": "editor"}).status_code == 200
    for hidden in (recs[0], recs[2]):
        assert client.post(f"/api/tasks/{hidden}/permissions",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "perm": "none"}).status_code == 200
    alone = _item(client, admin_id, a, "חיפה z3", cid, "עיריית חיפה")
    dupe = _item(client, admin_id, a, "מועצה z3", cid, "מועצה")

    mine = _preview(client, a, cid, b, admin_id).json()
    theirs = _preview(client, a, cid, b, guinea_id).json()
    assert (mine["matched"], mine["unmatched"], mine["ambiguous"]) == (1, 0, 1)
    # for guinea the hidden record is not a match at all…
    assert (theirs["matched"], theirs["unmatched"], theirs["ambiguous"]) == (1, 1, 0)
    assert _by_task(theirs["exceptions"])[alone]["reason"] == "no_match"
    # …and not a second answer either: "מועצה" is unique as far as they can see
    assert dupe not in _by_task(theirs["exceptions"])
    assert theirs["samples"][0]["after"]["id"] == recs[1]
    # nor does the fields endpoint count it
    assert _fields(client, a, b, admin_id).json()["fields"][0]["duplicates"] == 1
    assert _fields(client, a, b, guinea_id).json()["fields"][0]["duplicates"] == 0

    # and applying as guinea writes only the link they are entitled to
    assert _apply(client, a, cid, b, guinea_id).status_code == 200
    assert _cell(client, a, cid, dupe, admin_id) == [recs[1]]
    assert not _cell(client, a, cid, alone, admin_id)


def test_a_record_the_actor_cannot_see_cannot_resolve_an_exception_either(
        client, admin_id, guinea_id):
    a, b, cid, recs = _pair(client, admin_id, "z4", ["עיריית חיפה"])
    for bid, role in ((a, "admin"), (b, "editor")):
        assert client.post(f"/api/boards/{bid}/members",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "role": role}).status_code == 200
    assert client.post(f"/api/tasks/{recs[0]}/permissions",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "perm": "none"}).status_code == 200
    t = _item(client, admin_id, a, "פרויקט z4", cid, "אין כזה")
    assert _apply(client, a, cid, b, guinea_id).status_code == 200

    r = _resolve(client, a, cid, t, guinea_id, item_id=recs[0])
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "אין לך הרשאת צפייה בפריט שנבחר"
    assert not _cell(client, a, cid, t, admin_id)
    # the same id, from somebody who may see it, is accepted
    assert _resolve(client, a, cid, t, admin_id, item_id=recs[0]).status_code == 200


def test_the_endpoints_answer_the_right_refusal_for_the_wrong_argument(
        client, admin_id):
    """422 for a missing body, 404 for a parent that does not exist, 400 for an
    argument that does — never a generic 500 (invariant 4)."""
    a, b, cid, recs = _pair(client, admin_id, "z5", ["עיריית חיפה"])
    _item(client, admin_id, a, "פרויקט z5", cid, "עיריית חיפה")

    assert client.post(f"/api/boards/{a}/columns/{cid}/link-match",
                       headers=AS(admin_id)).status_code == 422
    assert _preview(client, a, cid, 0, admin_id).status_code == 400
    assert _preview(client, a, cid, 10 ** 9, admin_id).status_code == 404
    assert _preview(client, a, "col_nothing", b, admin_id).status_code == 404
    assert _preview(client, 10 ** 9, cid, b, admin_id).status_code == 404
    assert _fields(client, a, 0, admin_id).status_code == 400


def test_a_column_that_holds_no_value_of_its_own_cannot_become_a_link(
        client, admin_id):
    """A formula or a מזהה פריט has no words a person typed, so there is nothing
    to look for on the target board."""
    a, b, cid, recs = _pair(client, admin_id, "z6", ["עיריית חיפה"])
    r = _preview(client, a, "sys_item_id", b, admin_id)
    assert r.status_code in (400, 404), r.text


# ════════════════════════════════════════════════════════════════════════════
# what the board payload has to carry for the grid to draw any of this
# ════════════════════════════════════════════════════════════════════════════

def test_the_board_says_which_connect_column_has_a_conversion_open(client, admin_id):
    """The header's warning dot and "טיפול בחריגות (37)" are drawn off this, and
    a count fetched per column per render is a count nobody would notice going
    stale."""
    a, b, cid, recs = _pair(client, admin_id, "y1", ["עיריית חיפה"])
    _item(client, admin_id, a, "מותאם y1", cid, "עיריית חיפה")
    t = _item(client, admin_id, a, "חסר y1", cid, "אין כזה")
    conv_id = _apply(client, a, cid, b, admin_id).json()["conversion_id"]

    col = _coldef(client, a, cid, admin_id)
    # the counts are the exception list's — open + resolved — not the number of
    # cells the conversion kept. "טיפול בחריגות (1)" is what the header says,
    # and a matched cell is not something anybody has to handle.
    assert col["conversion"] == {"id": conv_id, "open": 1, "resolved": 0, "total": 1,
                                 "target_board_id": b, "match_field": "title"}
    assert _resolve(client, a, cid, t, admin_id, action="clear").status_code == 200
    # the last one closed it, and the key goes with it
    assert "conversion" not in _coldef(client, a, cid, admin_id)


def test_an_item_waiting_to_be_matched_carries_its_original_text_and_the_rest_do_not(
        client, admin_id):
    """The grid has to draw the words the cell used to say, or an unresolved
    exception looks exactly like an empty cell and the board appears to have
    eaten the column. It rides beside custom_fields rather than inside it,
    because a connect column must go on holding only item ids — a grid that
    found a string in a list of links would draw a broken chip.

    Absent, not {}, on an item with nothing pending: every item on every board
    that is not mid-conversion would otherwise carry the key.
    """
    a, b, cid, recs = _pair(client, admin_id, "y2", ["עיריית חיפה"],
                            type="dropdown",
                            options=["עיריית חיפה", "רשות העתיקות"])
    matched = _item(client, admin_id, a, "מותאם y2", cid, ["עיריית חיפה"])
    partial = _item(client, admin_id, a, "חלקי y2", cid,
                    ["עיריית חיפה", "רשות העתיקות"])
    empty = _item(client, admin_id, a, "ריק y2", cid, [])
    assert _apply(client, a, cid, b, admin_id).status_code == 200

    tasks = _tasks(client, a, admin_id)
    assert tasks[partial]["link_pending"] == {cid: "עיריית חיפה, רשות העתיקות"}
    for tid in (matched, empty):
        assert "link_pending" not in tasks[tid], tasks[tid].get("link_pending")
    assert (tasks[partial].get("custom_fields") or {}).get(cid) in (None, [])


def test_a_board_with_no_conversion_carries_the_key_on_nothing(client, admin_id):
    """The prefetch asks one question per board render and nothing at all when
    no conversion is open anywhere — this is the regression that would make
    every board payload grow a key."""
    a, b, cid, recs = _pair(client, admin_id, "y3", ["עיריית חיפה"])
    _item(client, admin_id, a, "פרויקט y3", cid, "עיריית חיפה")
    for t in _tasks(client, a, admin_id).values():
        assert "link_pending" not in t, t


# ════════════════════════════════════════════════════════════════════════════
# the holes a code review found while this file was green
#
# Every test below reproduces something the first forty-three did not ask.
# They were not wrong — they just all ran as the admin of both boards, with
# one word per cell, and never reverted a two-way conversion. Each of these
# names the question that was missing.
# ════════════════════════════════════════════════════════════════════════════

def _colids(client, bid, uid):
    return [c["id"] for c in client.get(f"/api/boards/{bid}", headers=AS(uid)).json()["columns"]]


def test_a_two_way_conversion_needs_board_admin_on_the_target_too(
        client, admin_id, guinea_id):
    """A two-way column CREATES a column on the other board, and creating a
    column there is an admin's act — PATCH /api/boards/{id} has refused it by
    name for as long as two-way columns have existed.

    This endpoint reached _ensure_mirrors by a different door, so a plain
    member of the organisation's "לקוחות" board could add a column every one of
    its members then sees. Same gate, same sentence. The one-way conversion is
    checked in the same test and by the same person: the refusal has to be
    about the column being created, not about them.
    """
    a, b, cid, recs = _pair(client, admin_id, "n1", ["עיריית חיפה"])
    assert client.post(f"/api/boards/{a}/members",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "role": "admin"}).status_code == 200
    assert client.post(f"/api/boards/{b}/members",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "role": "editor"}).status_code == 200
    t = _item(client, admin_id, a, "פרויקט n1", cid, "עיריית חיפה")
    before = _colids(client, b, admin_id)

    r = _apply(client, a, cid, b, guinea_id, two_way=True)
    assert r.status_code == 403, r.text
    assert "מנהל" in r.json()["detail"] and _board_name(client, b, admin_id) in r.json()["detail"]
    assert _colids(client, b, admin_id) == before, "a column was created on the target anyway"
    assert _coldef(client, a, cid, admin_id)["type"] == "text", "the source column changed"

    # the same person, the same boards, one-way: nothing is created over there,
    # so nothing is refused
    ok = _apply(client, a, cid, b, guinea_id, two_way=False)
    assert ok.status_code == 200, ok.text
    assert _cell(client, a, cid, t, admin_id) == [recs[0]]
    assert _colids(client, b, admin_id) == before


def test_a_viewer_on_the_target_board_cannot_make_it_two_way_either(
        client, admin_id, guinea_id):
    a, b, cid, recs = _pair(client, admin_id, "n2", ["עיריית חיפה"])
    for bid, role in ((a, "admin"), (b, "viewer")):
        assert client.post(f"/api/boards/{bid}/members",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "role": role}).status_code == 200
    _item(client, admin_id, a, "פרויקט n2", cid, "עיריית חיפה")
    before = _colids(client, b, admin_id)
    assert _apply(client, a, cid, b, guinea_id, two_way=True).status_code == 403
    assert _colids(client, b, admin_id) == before


def test_a_match_field_the_actor_may_not_see_is_not_offered_as_one(
        client, admin_id, guinea_id):
    """A lookup oracle on a column somebody was explicitly shut out of.

    The field list offered the column by name with its `filled` and
    `duplicates` counts, and then the preview would work on it: type a
    candidate ח.פ. into a column on your OWN board, run the preview, and
    `matched: 1` with the record's title in `samples` confirms whose number it
    is. No write, no audit line, on a column the target board's admin had set
    to "none" for exactly this person.
    """
    a = _board(client, admin_id, "מקור n3")
    b = _board(client, admin_id, "לקוחות n3")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    hp = _col(client, admin_id, b, type="text", title="ח.פ.")["id"]
    for bid, role in ((a, "admin"), (b, "editor")):
        assert client.post(f"/api/boards/{bid}/members",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "role": role}).status_code == 200
    assert client.post(f"/api/boards/{b}/columns/{hp}/permissions",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "perm": "none"}).status_code == 200
    _item(client, admin_id, b, "עיריית חיפה n3", hp, "500100200")
    _item(client, admin_id, a, "פרויקט n3", cid, "500100200")

    mine = _fields(client, a, b, admin_id).json()
    theirs = _fields(client, a, b, guinea_id).json()
    assert hp in [f["key"] for f in mine["fields"]], "the admin lost their own column"
    assert hp not in [f["key"] for f in theirs["fields"]], \
        "a column closed to this person was offered to identify records by"
    # and nothing of it leaks sideways either — not the label, not the counts
    assert not any(f["label"] == "ח.פ." for f in theirs["fields"]), theirs["fields"]

    # the board admin is unaffected: this is a per-person override, not a
    # column that stopped working
    assert _preview(client, a, cid, b, admin_id, match_field=hp).json()["matched"] == 1


def test_a_match_field_the_actor_may_not_see_answers_the_404_a_missing_one_does(
        client, admin_id, guinea_id):
    """404 and not 403, deliberately, and this test is here so nobody "fixes" it.

    A distinct refusal for "the column is there, you just may not use it" is
    the confirmation the oracle was after: walk the column ids of a board you
    are a member of, and 403-instead-of-404 maps every column somebody took
    away from you. Indistinguishable is the point.
    """
    a = _board(client, admin_id, "מקור n4")
    b = _board(client, admin_id, "לקוחות n4")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    hp = _col(client, admin_id, b, type="text", title="ח.פ.")["id"]
    for bid, role in ((a, "admin"), (b, "editor")):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": role})
    client.post(f"/api/boards/{b}/columns/{hp}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"})
    _item(client, admin_id, b, "עיריית חיפה n4", hp, "500100200")
    _item(client, admin_id, a, "פרויקט n4", cid, "500100200")

    denied = _preview(client, a, cid, b, guinea_id, match_field=hp)
    absent = _preview(client, a, cid, b, guinea_id, match_field="col_nothing_at_all")
    assert denied.status_code == 404, denied.text
    assert absent.status_code == 404, absent.text
    assert denied.json() == absent.json(), \
        "the refusal tells them the column is there — that is the oracle"
    # and the apply is shut too, not only the read
    assert _apply(client, a, cid, b, guinea_id, match_field=hp).status_code == 404
    assert _coldef(client, a, cid, admin_id)["type"] == "text"


def test_a_record_deleted_from_the_middle_of_a_multi_value_cell_is_noticed(
        client, admin_id):
    """Only the FIRST matched id was checked for liveness, so a dropdown that
    became three links lost the second one silently: the cell went on pointing
    at a record that was not there, and the conversion closed happily over it.
    The whole matched list is checked now."""
    a, b, cid, recs = _pair(client, admin_id, "n5", ["א", "ב", "ג"],
                            type="dropdown", options=["א", "ב", "ג"])
    t = _item(client, admin_id, a, "שלושה n5", cid, ["א", "ב", "ג"])
    assert _apply(client, a, cid, b, admin_id).json()["matched"] == 1
    assert _cell(client, a, cid, t, admin_id) == recs
    assert _exceptions(client, a, cid, admin_id).json()["open"] == 0

    # the SECOND of the three — the one the old scalar check could not see
    assert client.delete(f"/api/tasks/{recs[1]}?user_id={admin_id}").status_code == 200
    e = _exceptions(client, a, cid, admin_id).json()
    assert e["open"] == 1, e
    assert (e["rows"][0]["task_id"], e["rows"][0]["reason"]) == (t, "target_deleted")


def test_re_pointing_a_dead_link_leaves_the_cells_other_links_alone(
        client, admin_id):
    """Three links went in and one came out: the resolver wrote [chosen] over
    the whole cell, so answering "this one became that one" destroyed the two
    relationships that were perfectly fine. The cell is AMENDED — the dead end
    makes way for the chosen record, in its place, and everything still alive
    stays exactly where it was."""
    a, b, cid, recs = _pair(client, admin_id, "n6", ["א", "ב", "ג", "ד"],
                            type="dropdown", options=["א", "ב", "ג", "ד"])
    t = _item(client, admin_id, a, "שלושה n6", cid, ["א", "ב", "ג"])
    assert _apply(client, a, cid, b, admin_id).json()["matched"] == 1
    assert client.delete(f"/api/tasks/{recs[1]}?user_id={admin_id}").status_code == 200

    r = _resolve(client, a, cid, t, admin_id, item_id=recs[3])
    assert r.status_code == 200, r.text
    # א and ג survive, and ד stands where ב was — the order a multi-value cell
    # was converted in is part of what the cell said
    assert _cell(client, a, cid, t, admin_id) == [recs[0], recs[3], recs[2]]
    assert r.json()["closed"] is True


def test_clearing_a_dead_link_drops_only_the_dead_end(client, admin_id):
    """The same, said of a row whose cell has other links. "סמן כלא מותאם"
    answers the value that could not be matched. It is not "empty this cell":
    the two records still there were never in question."""
    a, b, cid, recs = _pair(client, admin_id, "n7", ["א", "ב", "ג"],
                            type="dropdown", options=["א", "ב", "ג"])
    t = _item(client, admin_id, a, "שלושה n7", cid, ["א", "ב", "ג"])
    assert _apply(client, a, cid, b, admin_id).json()["matched"] == 1
    assert client.delete(f"/api/tasks/{recs[1]}?user_id={admin_id}").status_code == 200

    r = _resolve(client, a, cid, t, admin_id, action="clear")
    assert r.status_code == 200, r.text
    assert _cell(client, a, cid, t, admin_id) == [recs[0], recs[2]]


def test_the_two_way_cell_is_amended_too_and_the_mirrors_follow(client, admin_id):
    """The same rule on the other write path. A two-way cell is ItemLink rows,
    not a list on the item, so "amend rather than replace" has to be true in
    both or it is true in neither."""
    a, b, cid, recs = _pair(client, admin_id, "n8", ["א", "ב", "ג", "ד"],
                            type="dropdown", options=["א", "ב", "ג", "ד"])
    t = _item(client, admin_id, a, "שלושה n8", cid, ["א", "ב", "ג"])
    assert _apply(client, a, cid, b, admin_id, two_way=True).json()["matched"] == 1
    mirror = _coldef(client, a, cid, admin_id)["connect"]["mirror"][str(b)]
    assert client.delete(f"/api/tasks/{recs[1]}?user_id={admin_id}").status_code == 200

    assert _resolve(client, a, cid, t, admin_id, item_id=recs[3]).status_code == 200
    # Set, not sequence, and only on this path: a two-way cell has nowhere to
    # keep an order of its own — _linked_ids orders it by ItemLink row id, "the
    # order the links were made" — so the record chosen today lands last however
    # it was passed. That is two-way linking's own long-standing behaviour and
    # not this conversion's to change; the place in the order is pinned on the
    # one-way path above, where the cell really does hold a list.
    assert sorted(_cell(client, a, cid, t, admin_id)) == \
        sorted([recs[0], recs[2], recs[3]]), "a surviving link was destroyed"
    assert recs[1] not in _cell(client, a, cid, t, admin_id)
    # and the far ends agree: the two that survived still point back, and the
    # newly chosen one now does
    for r in (recs[0], recs[2], recs[3]):
        assert _cell(client, b, mirror, r, admin_id) == [t], r


def test_a_conversion_row_from_before_the_list_column_still_notices_its_dead_target(
        client, admin_id):
    """`linked_task_ids` is a new column, so a conversion that was already open
    when the deployment rolled has rows carrying only the scalar. Those rows
    must still be checked — the fallback in _conversion_cell_links is the only
    thing standing between such a conversion and a cell silently pointing at
    nothing. Simulated by clearing the list the way those rows have it."""
    a, b, cid, recs = _pair(client, admin_id, "n9", ["עיריית חיפה"])
    t = _item(client, admin_id, a, "פרויקט n9", cid, "עיריית חיפה")
    conv_id = _apply(client, a, cid, b, admin_id).json()["conversion_id"]

    with Session(cityos_main.engine) as db:
        row = (db.query(cityos_main.ColumnConversionCell)
                 .filter_by(conversion_id=conv_id, task_id=t).one())
        assert row.linked_task_ids == [recs[0]], "today's rows carry the list"
        row.linked_task_ids = None          # yesterday's do not
        db.commit()

    assert client.delete(f"/api/tasks/{recs[0]}?user_id={admin_id}").status_code == 200
    e = _exceptions(client, a, cid, admin_id).json()
    assert e["open"] == 1, e
    assert e["rows"][0]["reason"] == "target_deleted"
    assert e["rows"][0]["linked_task_id"] == recs[0]


def test_a_cell_that_holds_something_but_says_nothing_is_cleared_and_comes_back(
        client, admin_id):
    """A checkbox that is False, a text cell of spaces, a date nothing can
    parse: _cell_words reads them as no words, but they are not blank. They
    were left exactly where they were — the OLD type's value sitting under a
    column that is now a link — and with no conversion row, so a revert did not
    cover them and _serialize_task, which only filters a connect cell when it
    is a list, handed a bare False to the browser as a link cell's contents.

    They are cleared like any other unreadable cell, and the row they now get
    is what puts them back.
    """
    a = _board(client, admin_id, "מקור na")
    b = _board(client, admin_id, "לקוחות na")
    cid = _col(client, admin_id, a, type="checkbox", title="סומן")["id"]
    yes = _item(client, admin_id, b, "כן")
    off = _item(client, admin_id, a, "לא מסומן na", cid, False)
    on = _item(client, admin_id, a, "מסומן na", cid, True)
    blank = _item(client, admin_id, a, "ריק na", cid, None)
    assert _cell(client, a, cid, off, admin_id) is False, "the setup did not store False"

    assert _apply(client, a, cid, b, admin_id).status_code == 200
    # cleared — not left holding False under a connect column
    assert _cell(client, a, cid, off, admin_id) in (None, []), \
        _cell(client, a, cid, off, admin_id)
    assert _cell(client, a, cid, on, admin_id) == [yes]

    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 200, r.text
    # two rows: the False one and the matched one. The genuinely blank cell got
    # none, which is the boundary that keeps a sparse column's exception list
    # from being mostly blanks
    assert r.json()["restored"] == 2, r.json()
    assert _cell(client, a, cid, off, admin_id) is False, "False did not come back"
    assert _cell(client, a, cid, on, admin_id) is True
    assert _cell(client, a, cid, blank, admin_id) is None


def test_whitespace_that_is_not_a_value_is_kept_and_restored_too(client, admin_id):
    a, b, cid, recs = _pair(client, admin_id, "nb", ["עיריית חיפה"])
    spaces = _item(client, admin_id, a, "רווחים nb", cid, "   ")
    _item(client, admin_id, a, "מותאם nb", cid, "עיריית חיפה")
    assert _apply(client, a, cid, b, admin_id).status_code == 200
    assert _cell(client, a, cid, spaces, admin_id) in (None, [])
    assert _revert(client, a, cid, admin_id).status_code == 200
    assert _cell(client, a, cid, spaces, admin_id) == "   "


def test_a_revert_takes_back_the_mirror_column_the_conversion_created(
        client, admin_id):
    """The revert put the source column back and left the counterpart standing
    on the other board — an empty connect column on somebody else's board,
    named after yours, that nothing could explain."""
    a, b, cid, recs = _pair(client, admin_id, "nc", ["עיריית חיפה"])
    _item(client, admin_id, a, "פרויקט nc", cid, "עיריית חיפה")
    before = _colids(client, b, admin_id)

    assert _apply(client, a, cid, b, admin_id, two_way=True).status_code == 200
    after_apply = _colids(client, b, admin_id)
    assert len(after_apply) == len(before) + 1, (before, after_apply)

    assert _revert(client, a, cid, admin_id).status_code == 200
    assert _colids(client, b, admin_id) == before, \
        "the mirror the conversion made outlived the conversion"


def test_a_revert_leaves_a_column_the_target_board_already_had(client, admin_id):
    """And this is the half that matters. `created_cols` records what
    _ensure_mirrors actually appended, rather than inferring the mirror
    afterwards — inferring it would delete a column somebody already had, which
    is far worse than leaving residue behind."""
    a = _board(client, admin_id, "מקור nd")
    b = _board(client, admin_id, "לקוחות nd")
    made = _cols(client, admin_id, a, [
        {"type": "text", "title": "לקוחות"},
        {"type": "connect", "title": "קשר ישן",
         "connect": {"board_ids": [b], "multiple": True, "two_way": True}}])
    cid = next(c["id"] for c in made if c["type"] == "text")
    _item(client, admin_id, b, "עיריית חיפה nd")
    _item(client, admin_id, a, "פרויקט nd", cid, "עיריית חיפה nd")
    before = _colids(client, b, admin_id)          # already carries a mirror

    assert _apply(client, a, cid, b, admin_id, two_way=True).status_code == 200
    assert len(_colids(client, b, admin_id)) == len(before) + 1

    assert _revert(client, a, cid, admin_id).status_code == 200
    assert _colids(client, b, admin_id) == before, \
        "the revert took away a column the conversion did not create"


def test_a_cell_with_more_matches_than_a_cell_may_hold_is_an_ambiguity(
        client, admin_id, monkeypatch):
    """The one place this feature could drop a value. Every word found its
    record, the cell was reported `matched` by both the preview and the apply,
    and then _merge_link_ids capped the list silently (report=None) on the
    two-way write — so the tail went, with nothing anywhere saying so. Over the
    ceiling is a cardinality problem like any other: a person chooses."""
    monkeypatch.setenv("CITYOS_MAX_LINKS_PER_CELL", "2")
    a, b, cid, recs = _pair(client, admin_id, "ne", ["א", "ב", "ג"],
                            type="dropdown", options=["א", "ב", "ג"])
    over = _item(client, admin_id, a, "שלושה ne", cid, ["א", "ב", "ג"])
    under = _item(client, admin_id, a, "שניים ne", cid, ["א", "ב"])

    p = _preview(client, a, cid, b, admin_id, multiple=True).json()
    assert (p["matched"], p["ambiguous"]) == (1, 1), p
    assert _by_task(p["exceptions"])[over]["reason"] == "too_many_values"

    r = _apply(client, a, cid, b, admin_id, multiple=True, two_way=True)
    assert r.status_code == 200, r.text
    assert _counts(r.json()) == _counts(p)
    assert not _cell(client, a, cid, over, admin_id), "the tail was dropped quietly"
    assert _cell(client, a, cid, under, admin_id) == recs[:2]


def test_the_exception_list_shows_each_reader_only_the_candidates_they_may_see(
        client, admin_id, guinea_id):
    """The candidates were worked out from what the admin who RAN the
    conversion could see, and then handed to whoever read the list. A second
    admin is a different reader: a title they were refused must not arrive
    because somebody else once could see it."""
    a, b, cid, recs = _pair(client, admin_id, "nf", ["מועצה", "מועצה"])
    t = _item(client, admin_id, a, "פרויקט nf", cid, "מועצה")
    for bid, role in ((a, "admin"), (b, "editor")):
        assert client.post(f"/api/boards/{bid}/members",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "role": role}).status_code == 200
    assert _apply(client, a, cid, b, admin_id).json()["ambiguous"] == 1
    assert client.post(f"/api/tasks/{recs[1]}/permissions",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "perm": "none"}).status_code == 200

    mine = _exceptions(client, a, cid, admin_id).json()["rows"][0]
    theirs = _exceptions(client, a, cid, guinea_id).json()["rows"][0]
    assert [k["id"] for k in mine["candidates"]] == recs
    assert [k["id"] for k in theirs["candidates"]] == [recs[0]], theirs["candidates"]
    assert all(k["title"] for k in theirs["candidates"]), "a visible candidate lost its title"
    # the row is still there to be answered — it is the candidate that is gone,
    # not the work
    assert theirs["task_id"] == t and theirs["reason"] == "several"


def test_a_board_the_actor_is_not_in_refuses_without_naming_it(client, admin_id,
                                                               guinea_id):
    """The organisation gate was asked before membership, and it names the
    board it refuses — "לוח 'X' שייך לארגון אחר", as a 400. So anybody who
    administers any one board could walk target_board_id upwards and read out
    the name of every board in every other organisation on the deployment.
    A board they may not open does not get to tell them why.
    """
    a, b, cid, recs = _pair(client, admin_id, "ng", ["עיריית חיפה"])
    assert client.post(f"/api/boards/{a}/members",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "role": "admin"}).status_code == 200
    _item(client, admin_id, a, "פרויקט ng", cid, "עיריית חיפה")
    secret = _board(client, admin_id, "תכנית הנדסה סודית ng")

    with Session(cityos_main.engine) as db:
        row = db.query(cityos_main.Board).filter_by(id=secret).one()
        was = row.organization_id
        row.organization_id = (was or 0) + 9999
        db.commit()
    try:
        for r in (_fields(client, a, secret, guinea_id),
                  _preview(client, a, cid, secret, guinea_id),
                  _apply(client, a, cid, secret, guinea_id)):
            assert r.status_code == 403, (r.status_code, r.text)
            body = r.text
            assert "סודית" not in body and "ארגון אחר" not in body, body
            assert r.json()["detail"] == "אין לך גישה ללוח היעד"
        # a member of it is told the real reason — that refusal is legitimate,
        # it is about a board they can already see
        assert client.post(f"/api/boards/{secret}/members",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "role": "editor"}).status_code == 200
        told = _preview(client, a, cid, secret, guinea_id)
        assert told.status_code == 400, told.text
        assert "ארגון אחר" in told.json()["detail"], told.text
    finally:
        with Session(cityos_main.engine) as db:
            db.query(cityos_main.Board).filter_by(id=secret).one().organization_id = was
            db.commit()


# ════════════════════════════════════════════════════════════════════════════
# the undo is available precisely while using it is a no-op to anybody's work
#
# An all-matched conversion stays open — it has to, or a record deleted next
# month could never be surfaced — and for a long time that meant the undo
# stayed armed with it. Months later, over a column in daily use, one POST
# discarded the links people had re-pointed and wrote year-old text back.
#
# Closing the conversion when there is nothing to resolve was the obvious fix
# and is the wrong one; four tests above apply a zero-exception conversion and
# then undo it, which is exactly what an admin does in the minute after
# running it against the wrong board. What actually makes the undo unsafe is
# not time passing and not the absence of exceptions — it is somebody having
# touched the column. That is what is asked now, and these pin both answers.
# ════════════════════════════════════════════════════════════════════════════

def test_an_untouched_conversion_can_still_be_undone(client, admin_id):
    """The 200 side of the guard, on the shape that has no exceptions at all.
    Every cell matched, nobody has touched the column, so the stored originals
    are still the whole truth about it and putting them back costs nobody
    anything."""
    a, b, cid, recs = _pair(client, admin_id, "u1", ["עיריית חיפה"])
    t = _item(client, admin_id, a, "פרויקט u1", cid, "עיריית חיפה")
    assert _apply(client, a, cid, b, admin_id).json()["matched"] == 1
    assert _exceptions(client, a, cid, admin_id).json()["open"] == 0

    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 200, r.text
    assert _coldef(client, a, cid, admin_id)["type"] == "text"
    assert _cell(client, a, cid, t, admin_id) == "עיריית חיפה"


def test_a_link_re_pointed_by_hand_disarms_the_undo(client, admin_id):
    """And the 400 side, which is the whole point of the guard: the revert's
    own docstring has always promised not to overwrite links somebody has
    since chosen by hand, and that promise was guarded on a status an
    all-matched conversion never reaches. Refused means refused — the column
    is still a link column and the hand-made choice is still in the cell."""
    a, b, cid, recs = _pair(client, admin_id, "u2", ["עיריית חיפה", "רשות העתיקות"])
    t = _item(client, admin_id, a, "פרויקט u2", cid, "עיריית חיפה")
    assert _apply(client, a, cid, b, admin_id).json()["matched"] == 1
    assert _cell(client, a, cid, t, admin_id) == [recs[0]]

    # somebody decides it was the other one, long after the conversion ran
    assert client.patch(f"/api/tasks/{t}", json={"user_id": admin_id,
                                                 "custom_fields": {cid: [recs[1]]}}
                        ).status_code == 200

    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == ("מאז ההמרה שונו קישורים בעמודה הזו — "
                                  "ביטול ההמרה היה מוחק אותם")
    assert _coldef(client, a, cid, admin_id)["type"] == "connect"
    assert _cell(client, a, cid, t, admin_id) == [recs[1]], \
        "the undo was refused and still took the choice"
    # and the conversion is still open, not quietly spent by the attempt
    assert _exceptions(client, a, cid, admin_id).status_code == 200


def test_a_link_added_to_a_cell_the_conversion_left_empty_disarms_it_too(
        client, admin_id):
    """A cell that was an exception holds nothing when the apply is done. A
    link made in it afterwards is somebody's own work in exactly the same
    sense, and the revert would drop it on the floor on its way back to
    text."""
    a, b, cid, recs = _pair(client, admin_id, "u3", ["עיריית חיפה"])
    t = _item(client, admin_id, a, "חסר u3", cid, "אין כזה")
    assert _apply(client, a, cid, b, admin_id).json()["unmatched"] == 1
    assert not _cell(client, a, cid, t, admin_id)

    assert client.patch(f"/api/tasks/{t}", json={"user_id": admin_id,
                                                 "custom_fields": {cid: [recs[0]]}}
                        ).status_code == 200
    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 400, r.text
    assert _cell(client, a, cid, t, admin_id) == [recs[0]]


def test_a_link_added_from_the_target_board_disarms_the_undo_too(client, admin_id):
    """A two-way link has two ends and either of them is where it was made.
    Reading the cell from the source board's custom_fields would have seen
    nothing — a two-way cell does not live there — so the guard reads ItemLink
    for a two-way column, and an edit made by somebody who never opened the
    source board counts the same."""
    a, b, cid, recs = _pair(client, admin_id, "u4", ["עיריית חיפה"])
    t = _item(client, admin_id, a, "פרויקט u4", cid, "עיריית חיפה")
    spare = _item(client, admin_id, a, "עוד פרויקט u4")
    assert _apply(client, a, cid, b, admin_id, two_way=True).json()["matched"] == 1
    mirror = _coldef(client, a, cid, admin_id)["connect"]["mirror"][str(b)]

    # from the TARGET board: the customer is attached to a second project
    assert client.patch(f"/api/tasks/{recs[0]}",
                        json={"user_id": admin_id,
                              "custom_fields": {mirror: [t, spare]}}).status_code == 200
    assert sorted(_cell(client, b, mirror, recs[0], admin_id)) == sorted([t, spare])

    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 400, r.text
    assert sorted(_cell(client, b, mirror, recs[0], admin_id)) == sorted([t, spare]), \
        "the refused undo still unpicked the far end"


def test_unresolved_exceptions_do_not_disarm_the_undo(client, admin_id):
    """The guard asks whether anybody TOUCHED the column, not whether there is
    work left in it. A conversion that produced thirty exceptions and that
    nobody has answered is the single most likely thing an admin undoes."""
    a, b, cid, recs = _pair(client, admin_id, "u5", ["עיריית חיפה", "מועצה", "מועצה"])
    good = _item(client, admin_id, a, "מותאם u5", cid, "עיריית חיפה")
    miss = _item(client, admin_id, a, "חסר u5", cid, "אין כזה")
    dupe = _item(client, admin_id, a, "כפול u5", cid, "מועצה")
    assert _exceptions(client, a, cid, admin_id).status_code == 404
    assert _apply(client, a, cid, b, admin_id).status_code == 200
    assert _exceptions(client, a, cid, admin_id).json()["open"] == 2

    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 200, r.text
    for t, v in ((good, "עיריית חיפה"), (miss, "אין כזה"), (dupe, "מועצה")):
        assert _cell(client, a, cid, t, admin_id) == v


def test_an_exception_answered_through_the_resolver_does_not_disarm_it_either(
        client, admin_id):
    """The resolver keeps `linked_task_ids` current as it writes, so what it
    did is part of what the conversion wrote rather than drift against it.
    A guard that could not tell its own resolver from a stranger would make
    the undo unreachable the moment anybody started the work."""
    a, b, cid, recs = _pair(client, admin_id, "u6", ["עיריית חיפה", "רשות העתיקות"])
    miss = _item(client, admin_id, a, "חסר u6", cid, "אין כזה")
    other = _item(client, admin_id, a, "עוד חסר u6", cid, "גם אין")
    assert _apply(client, a, cid, b, admin_id).json()["unmatched"] == 2

    assert _resolve(client, a, cid, miss, admin_id, item_id=recs[1]).status_code == 200
    assert _cell(client, a, cid, miss, admin_id) == [recs[1]]
    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 200, r.text
    assert _cell(client, a, cid, miss, admin_id) == "אין כזה"
    assert _cell(client, a, cid, other, admin_id) == "גם אין"


def test_the_guard_does_not_cost_the_watch_on_a_deleted_record(client, admin_id):
    """The reason an all-matched conversion stays open in the first place. The
    guard must not have turned that into a conversion that is open, unusable
    and unwatchable — a record deleted afterwards is still listed, still
    carries its dead id, and can still be re-pointed."""
    a, b, cid, recs = _pair(client, admin_id, "u7", ["עיריית חיפה", "רשות העתיקות"])
    t = _item(client, admin_id, a, "פרויקט u7", cid, "עיריית חיפה")
    assert _apply(client, a, cid, b, admin_id).json()["matched"] == 1
    assert client.delete(f"/api/tasks/{recs[0]}?user_id={admin_id}").status_code == 200

    e = _exceptions(client, a, cid, admin_id).json()
    assert e["open"] == 1 and e["rows"][0]["reason"] == "target_deleted"
    assert e["rows"][0]["linked_task_id"] == recs[0]
    done = _resolve(client, a, cid, t, admin_id, item_id=recs[1])
    assert done.status_code == 200, done.text
    assert done.json()["closed"] is True
    assert _cell(client, a, cid, t, admin_id) == [recs[1]]


def test_marking_a_row_unmatched_keeps_a_link_somebody_made_by_hand(
        client, admin_id):
    """What the button's new wording describes, and why it was renamed.

    "סמן כלא מותאם" answers the ROW — this value has no record, stop asking —
    and leaves the cell to whoever has been working in it. The alternative,
    emptying the cell so the old label "השאר ריק" would be literally true,
    means destroying a person's own link to make a button's wording honest.
    It is the same code path that lets `clear` on a target_deleted row keep
    the two live links beside the dead one.
    """
    a, b, cid, recs = _pair(client, admin_id, "u8", ["עיריית חיפה"])
    t = _item(client, admin_id, a, "חסר u8", cid, "אין כזה")
    assert _apply(client, a, cid, b, admin_id).json()["unmatched"] == 1
    assert not _cell(client, a, cid, t, admin_id)

    # between the apply and the resolver, somebody linked it themselves
    assert client.patch(f"/api/tasks/{t}", json={"user_id": admin_id,
                                                 "custom_fields": {cid: [recs[0]]}}
                        ).status_code == 200

    r = _resolve(client, a, cid, t, admin_id, action="clear")
    assert r.status_code == 200, r.text
    assert r.json()["closed"] is True, "the row was not answered"
    assert _cell(client, a, cid, t, admin_id) == [recs[0]], \
        "marking the row unmatched threw away a link somebody chose"
    # the row is off the list, which is what the action was for
    assert _exceptions(client, a, cid, admin_id).status_code == 404
    assert "link_pending" not in _tasks(client, a, admin_id)[t]


def test_a_board_can_be_its_own_target(client, admin_id):
    """A "מנהל התיק" column naming another item on the same board. Nothing
    anywhere else in the product refuses a connect column pointing home, so
    refusing it here would be a restriction this feature invented.

    The bug was a stale snapshot: the definition list was captured before
    _ensure_mirrors appended the counterpart and then written back over it, so
    the mirror map named a column that was not on the board and the cell could
    hold no two-way link at all.
    """
    a = _board(client, admin_id, "מקור ua")
    cid = _col(client, admin_id, a, type="text", title="מנהל התיק")["id"]
    boss = _item(client, admin_id, a, "רינה ua")
    sub = _item(client, admin_id, a, "פרויקט ua", cid, "רינה ua")
    before = _colids(client, a, admin_id)

    r = _apply(client, a, cid, a, admin_id, two_way=True)
    assert r.status_code == 200, r.text
    assert r.json()["matched"] == 1 and r.json()["target_board_id"] == a

    col = _coldef(client, a, cid, admin_id)
    mirror = col["connect"]["mirror"][str(a)]
    assert mirror in _colids(client, a, admin_id), \
        "the mirror map names a column that is not on the board"
    assert len(_colids(client, a, admin_id)) == len(before) + 1
    assert _cell(client, a, cid, sub, admin_id) == [boss]
    assert _cell(client, a, mirror, boss, admin_id) == [sub], "the reverse was never written"

    assert _revert(client, a, cid, admin_id).status_code == 200
    assert _colids(client, a, admin_id) == before
    assert _cell(client, a, cid, sub, admin_id) == "רינה ua"


def test_the_mirror_the_revert_removes_is_logged_and_binned_on_the_target_board(
        client, admin_id):
    """A column disappearing from a board is a thing that board's log says and
    its column bin can undo. This one disappears from somebody ELSE's board —
    the one place an unexplained deletion is least recoverable — and it went
    through neither until now."""
    a, b, cid, recs = _pair(client, admin_id, "ub", ["עיריית חיפה"])
    _item(client, admin_id, a, "פרויקט ub", cid, "עיריית חיפה")
    assert _apply(client, a, cid, b, admin_id, two_way=True).status_code == 200
    mirror = _coldef(client, a, cid, admin_id)["connect"]["mirror"][str(b)]
    assert _revert(client, a, cid, admin_id).status_code == 200
    assert mirror not in _colids(client, b, admin_id)

    rows = client.get(f"/api/boards/{b}/activity", headers=AS(admin_id)).json()["activity"]
    hit = [r for r in rows if r["field"] == "column" and r["action"] == "delete"]
    assert len(hit) == 1, rows
    assert "ביטול ההמרה" in hit[0]["new"], hit[0]["new"]
    assert _board_name(client, a, admin_id) in hit[0]["new"], hit[0]["new"]
    # binned, so it is restorable like any other deleted column
    assert hit[0]["can_restore_column"] is True
    back = client.post(f"/api/boards/{b}/columns/restore",
                       json={"log_id": hit[0]["id"], "user_id": admin_id})
    assert back.status_code == 200, back.text
    assert mirror in _colids(client, b, admin_id)


# ════════════════════════════════════════════════════════════════════════════
# ROUND 2 — השוואה חכמה, the tier ladder
#
# The exact rule was correct and, on the board it was finally run against,
# useless: 474 of 476 cells came back unmatched, and essentially every one of
# them was a match a person reads at a glance — 'אשדוד - עיריה' beside a
# record called 'אשדוד', 'קרן קיימת לישראל' beside 'קק״ל'. The user asked for
# containment and acronyms, so there is now a ladder of tiers.
#
# Two rules hold it together and everything below is one of them:
#
#   · only tiers 0 and 1 LINK. They join two spellings of one string. Tiers
#     2-4 change which words are being compared, which is a judgement, so they
#     propose — `suggested` — and a person accepts in bulk or row by row.
#     "אין לנחש התאמות" survives, because a proposal somebody confirmed is not
#     a guess.
#   · a tier is taken only when it yields EXACTLY ONE candidate, and two or
#     more ENDS the walk. No falling through to a looser tier hoping for a
#     cleaner answer — that is how a precise rule becomes a sloppy one, and it
#     is the difference between proposing 'ראשון לציון' for a municipal
#     company and refusing to.
# ════════════════════════════════════════════════════════════════════════════

SMART = dict(smart=True)


def _tier_of(payload, key, task_id):
    return next((r for r in payload[key] if r["task_id"] == task_id), None)


# ── the tiers that link by themselves ───────────────────────────────────────

def test_punctuation_and_ktiv_are_one_name_spelled_twice_and_link(client, admin_id):
    """Tier 1, on the shapes the real board actually holds. The gershayim in
    'בע"מ', the hyphens in 'מודיעין-מכבים-רעות', the doubled yod in
    עירייה/עיריה: same letters, same order, same words in the same places.
    Refusing to join those would be pedantry, not caution."""
    a, b, cid, recs = _pair(client, admin_id, "t1",
                            ["מי יבנה בעמ", "מודיעין-מכבים-רעות", "פתח תקווה"])
    same = _item(client, admin_id, a, "גרשיים t1", cid, 'מי יבנה בע"מ')
    hyph = _item(client, admin_id, a, "מקפים t1", cid, "מודיעין מכבים רעות")
    ktiv = _item(client, admin_id, a, "כתיב t1", cid, "פתח תקוה")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert p["matched"] == 3, p
    by = {r["task_id"]: r for r in p["samples"]}
    assert by[same]["after"]["title"] == "מי יבנה בעמ"
    assert by[hyph]["after"]["title"] == "מודיעין-מכבים-רעות"
    assert by[ktiv]["after"]["title"] == "פתח תקווה"
    assert {by[t]["tier"] for t in (same, hyph, ktiv)} == {"punct"}

    assert _apply(client, a, cid, b, admin_id).status_code == 200
    for t, r in ((same, recs[0]), (hyph, recs[1]), (ktiv, recs[2])):
        assert _cell(client, a, cid, t, admin_id) == [r]


def test_a_hyphen_is_normalised_to_a_space_and_never_split_on(client, admin_id):
    """The first idea was to split at the hyphen, and it is wrong: the target
    side holds 'מודיעין-מכבים-רעות', one town written with two of them, and
    splitting would have left 'מודיעין' and lost the rest — then matched some
    other town called that."""
    a, b, cid, recs = _pair(client, admin_id, "t2",
                            ["מודיעין-מכבים-רעות", "מודיעין"])
    t = _item(client, admin_id, a, "מקף t2", cid, "מודיעין מכבים רעות - עיריה")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    sug = _tier_of(p, "suggestions", t)
    assert sug is not None, p
    # the WHOLE name, not the first word of it
    assert [c["title"] for c in sug["candidates"]] == ["מודיעין-מכבים-רעות"]
    assert sug["tier"] == "descriptor"


# ── the tiers that only propose ─────────────────────────────────────────────

def test_the_descriptor_tier_proposes_and_does_not_link(client, admin_id):
    """416 of 476 cells on the real board are a town followed by what kind of
    body it is, either after a hyphen or as a bare prefix. Both shapes become
    ordinary words once the hyphen is a space, and the descriptor comes off
    both sides."""
    a, b, cid, recs = _pair(client, admin_id, "t3",
                            ["אשדוד", "נהריה", "בית דגן", "ירוחם"])
    after = _item(client, admin_id, a, "אחרי t3", cid, "אשדוד - עיריה")
    before = _item(client, admin_id, a, "לפני t3", cid, "עירית נהריה")
    twodeep = _item(client, admin_id, a, "שניים t3", cid, "בית דגן - מועצה מקומית")
    plain = _item(client, admin_id, a, "רגיל t3", cid, "ירוחם מועצה מקומית")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert (p["matched"], p["suggested"], p["unmatched"]) == (0, 4, 0), p
    for t, want in ((after, "אשדוד"), (before, "נהריה"),
                    (twodeep, "בית דגן"), (plain, "ירוחם")):
        sug = _tier_of(p, "suggestions", t)
        assert sug["tier"] == "descriptor", (t, sug)
        assert [c["title"] for c in sug["candidates"]] == [want]

    # and applying without accepting writes none of them
    assert _apply(client, a, cid, b, admin_id).json()["suggested"] == 4
    for t in (after, before, twodeep, plain):
        assert not _cell(client, a, cid, t, admin_id)


def test_the_acronym_tier_proposes_from_whichever_side_is_long(client, admin_id):
    """קק״ל is the user's own example. It earns nothing on her board, which
    the backend said out loud rather than claiming otherwise — so it is pinned
    on data built for it, and will stay correct for the board where it does."""
    # two independent pairs, one read from each end: a long cell against a
    # short record, and a short cell against a long one
    a, b, cid, recs = _pair(client, admin_id, "t4",
                            ["קק״ל", "אגודת הסטודנטים הארצית"])
    long_cell = _item(client, admin_id, a, "ארוך t4", cid, "קרן קיימת לישראל")
    short_cell = _item(client, admin_id, a, "קצר t4", cid, "אהה")   # א+ה+ה, the first letter of each word

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert p["suggested"] == 2, p
    assert _tier_of(p, "suggestions", long_cell)["tier"] == "acronym"
    assert [c["title"] for c in _tier_of(p, "suggestions", long_cell)["candidates"]] \
        == ["קק״ל"]
    assert _tier_of(p, "suggestions", short_cell)["tier"] == "acronym"
    assert [c["title"] for c in _tier_of(p, "suggestions", short_cell)["candidates"]] \
        == ["אגודת הסטודנטים הארצית"]


def test_the_contains_tier_is_a_token_subset_and_never_a_substring(client, admin_id):
    """A token subset, strictly. As a substring "גת" would reach "קריית גת"
    and "רמת גן" would reach "רמת גן הירוקה" — letters inside words are not
    words, and a tier that cannot tell the difference is a tier that proposes
    the wrong town."""
    a, b, cid, recs = _pair(client, admin_id, "t5", ["מרכז הספורט", "גת"])
    subset = _item(client, admin_id, a, "מוכל t5", cid, "מרכז הספורט העירוני")
    inside = _item(client, admin_id, a, "בתוך t5", cid, "מגתה")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    sug = _tier_of(p, "suggestions", subset)
    assert sug is not None and sug["tier"] == "contains", p
    assert [c["title"] for c in sug["candidates"]] == ["מרכז הספורט"]
    # "מגתה" contains the letters of "גת" and shares no WORD with it
    assert _tier_of(p, "suggestions", inside) is None, p["suggestions"]
    assert _tier_of(p, "exceptions", inside)["reason"] == "no_match"


# ── the one-candidate rule, which is what keeps the ladder honest ───────────

def test_a_tier_that_answers_twice_stops_the_walk_instead_of_falling_through(
        client, admin_id):
    """The heart of it. Two records answering at tier 2 is genuine ambiguity,
    and letting tier 3 or 4 overrule it would be the sloppier rule beating the
    stricter one. The walk stops, the candidates are reported, nothing is
    proposed and nothing is linked."""
    a, b, cid, recs = _pair(client, admin_id, "t6", ["חדרה", "עיריית חדרה"])
    t = _item(client, admin_id, a, "כפול t6", cid, "חדרה - מועצה")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert (p["matched"], p["suggested"], p["ambiguous"]) == (0, 0, 1), p
    exc = _tier_of(p, "exceptions", t)
    assert (exc["outcome"], exc["reason"]) == ("ambiguous", "several")
    assert sorted(c["id"] for c in exc["candidates"]) == sorted(recs)
    assert _apply(client, a, cid, b, admin_id).status_code == 200
    assert not _cell(client, a, cid, t, admin_id)


def test_a_town_shared_by_seven_municipal_companies_is_an_ambiguity(
        client, admin_id):
    """The danger case, and the reason `contains` is safe to have at all.

    The target board holds municipal companies beside the municipalities that
    own them. "אשקלון" as a token subset reaches every one of them, and the
    only thing between that and six wrong links is the rule that a tier
    answering more than once reports the candidates instead of choosing.
    """
    a, b, cid, recs = _pair(client, admin_id, "t7",
                            ['חכ"ל אשקלון', "מי אשקלון", "חוף אשקלון",
                             "החברה העירונית אשקלון", "מרינה אשקלון",
                             "נמל אשקלון"])
    t = _item(client, admin_id, a, "עיר t7", cid, "אשקלון")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert (p["matched"], p["suggested"]) == (0, 0), p
    exc = _tier_of(p, "exceptions", t)
    assert (exc["outcome"], exc["reason"]) == ("ambiguous", "several")
    assert len(exc["candidates"]) == len(recs), exc["candidates"]
    assert _apply(client, a, cid, b, admin_id).status_code == 200
    assert not _cell(client, a, cid, t, admin_id), "one of six was picked"


def test_a_municipal_company_must_never_reach_its_town_on_a_ticked_tier(
        client, admin_id):
    """THE guard-rail, and it is a test on its own for a reason.

    עירונית and כלכלית are deliberately NOT in _ORG_DESCRIPTORS: they are what
    tells a municipal company from the municipality that owns it. Drop them
    and 'חברה עירונית ראשון לציון' reads as 'ראשון לציון' at the DESCRIPTOR
    tier — which arrives pre-ticked, so an admin pressing one button attaches
    five wrong customers to five projects.

    It used to be the second half of the test below, and when `abbrev` landed
    the first half started failing — so this assertion stopped executing
    altogether and protected nothing for as long as that lasted. A guard-rail
    that can be taken out by an unrelated assertion two lines above it is not
    a guard-rail. It is its own test now, and it must stay one.
    """
    a, b, cid, recs = _pair(client, admin_id, "t8a", ["ראשון לציון"])
    full = _item(client, admin_id, a, "חברה t8a", cid, "חברה עירונית ראשון לציון")
    short = _item(client, admin_id, a, "חב t8a", cid, "חב' עירונית ראשון לציון")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert p["matched"] == 0, "a municipal company linked itself to its town"
    for t in (full, short):
        sug = _tier_of(p, "suggestions", t)
        assert sug is not None, (t, p)
        assert sug["tier"] == "contains", \
            "a municipal company reached its town on a tier an admin ticks"
    tiers = {x["key"]: x for x in p["tiers"]}
    assert tiers["contains"]["default_on"] is False
    assert tiers["descriptor"]["count"] == 0, \
        "the company was read as the town once the descriptors came off"


def test_a_municipal_company_is_proposed_over_the_town_that_owns_it(
        client, admin_id):
    """'חב׳ עירונית ראשון לציון' and 'ראשון לציון' are two different
    customers, and a project attached to the wrong one is found months later.

    This used to pin that with BOTH on the board the cell is an ambiguity
    between them. The user then asked for the opposite and the better thing —
    "חב' עירונית ראשון לציון צריך להתאים ל החברה העירונית ראשלצ" — and the
    `abbrev` tier answers it: the cell resolves to the COMPANY, alone. What
    the pair of tests exists to defend is unharmed and in fact stronger,
    which is why this half is rewritten rather than deleted — with
    abbreviation consuming both sides entirely the town is not merely the
    wrong answer, it is not a candidate.
    """
    a, b, cid, recs = _pair(client, admin_id, "t8",
                            ["ראשון לציון", "חברה עירונית ראשון לציון"])
    town, company = recs
    t = _item(client, admin_id, a, "חברה t8", cid, "חב\' עירונית ראשון לציון")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert p["matched"] == 0, "an abbreviation linked itself without being asked"
    assert p["suggested"] == 1 and p["ambiguous"] == 0, p
    sug = _tier_of(p, "suggestions", t)
    assert sug["tier"] == "abbrev", sug
    assert [c["id"] for c in sug["candidates"]] == [company], \
        "the company is what the cell says and what it should reach"
    assert town not in [c["id"] for c in sug["candidates"]], \
        "the town is still being offered as an answer"
    assert _tier_of(p, "exceptions", t) is None, p["exceptions"]


def test_the_identity_words_are_never_stripped(client, admin_id):
    """קריית גת minus קריית is גת, a different place entirely. The words that
    look like the same sort of prefix as a descriptor and are the opposite —
    they are the identity — and dropping one would propose the wrong town."""
    a, b, cid, recs = _pair(client, admin_id, "t9",
                            ["קריית גת", "גת", "קיבוץ יגור", "יגור",
                             "מושב נהלל", "נהלל", "בית דגן", "דגן",
                             "נווה שאנן", "שאנן", "רמת ישי", "ישי",
                             "גבעת שמואל", "שמואל", "כפר סבא", "סבא"])
    pairs = [("קריית גת - עירייה", "קריית גת"), ("קיבוץ יגור - ועד", "קיבוץ יגור"),
             ("מושב נהלל - ועד", "מושב נהלל"), ("בית דגן - מועצה מקומית", "בית דגן"),
             ("נווה שאנן - ועד", "נווה שאנן"), ("רמת ישי - מועצה", "רמת ישי"),
             ("גבעת שמואל - עיריה", "גבעת שמואל"), ("כפר סבא - עיריה", "כפר סבא")]
    ids = {v: _item(client, admin_id, a, "src " + v + " t9", cid, v)
           for v, _ in pairs}

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert p["suggested"] == len(pairs), p
    for v, want in pairs:
        sug = _tier_of(p, "suggestions", ids[v])
        assert [c["title"] for c in sug["candidates"]] == [want], (v, sug)
    assert p["ambiguous"] == 0, "an identity word was dropped and collided"


# ── accepting what was proposed ─────────────────────────────────────────────

def _suggest_pair(client, admin_id, tag):
    """A board with one descriptor suggestion and one contains suggestion."""
    a, b, cid, recs = _pair(client, admin_id, tag, ["אשדוד", "נמל חדש"])
    desc = _item(client, admin_id, a, "תיאור " + tag, cid, "אשדוד - עיריה")
    cont = _item(client, admin_id, a, "הכלה " + tag, cid, "נמל חדש גדול")
    return a, b, cid, recs, desc, cont


def test_a_suggestion_nobody_accepted_is_an_ordinary_exception(client, admin_id):
    """With its proposal attached, so the resolver opens with the right record
    already named and one click answers it."""
    a, b, cid, recs, desc, cont = _suggest_pair(client, admin_id, "ta")
    r = _apply(client, a, cid, b, admin_id)
    assert r.status_code == 200, r.text
    assert (r.json()["matched"], r.json()["suggested"]) == (0, 2)
    assert not _cell(client, a, cid, desc, admin_id)
    assert not _cell(client, a, cid, cont, admin_id)

    rows = _by_task(_exceptions(client, a, cid, admin_id).json()["rows"])
    assert rows[desc]["outcome"] == "suggested" and rows[desc]["reason"] == "descriptor"
    assert [c["id"] for c in rows[desc]["candidates"]] == [recs[0]]
    assert rows[cont]["outcome"] == "suggested" and rows[cont]["reason"] == "contains"
    # and the cell still shows the words it used to say
    assert _tasks(client, a, admin_id)[desc]["link_pending"] == {cid: "אשדוד - עיריה"}


def test_accepting_by_tier_takes_the_reliable_ones_and_leaves_the_rest(
        client, admin_id):
    """Measured on the real board, `descriptor` proposed 414 and was right on
    essentially all of them while `contains` proposed 24 and was wrong on
    five. One button for both would hand an admin the good 414 and the bad 5
    in the same click, so the request names the tiers it is accepting."""
    a, b, cid, recs, desc, cont = _suggest_pair(client, admin_id, "tb")
    r = _apply(client, a, cid, b, admin_id, accept_suggested=["descriptor"])
    assert r.status_code == 200, r.text
    assert (r.json()["matched"], r.json()["suggested"]) == (1, 1)
    assert _cell(client, a, cid, desc, admin_id) == [recs[0]]
    assert not _cell(client, a, cid, cont, admin_id), "an unaccepted tier was linked"
    assert list(_by_task(_exceptions(client, a, cid, admin_id).json()["rows"])) == [cont]


def test_accepting_everything_is_still_available_for_a_board_that_wants_it(
        client, admin_id):
    a, b, cid, recs, desc, cont = _suggest_pair(client, admin_id, "tc")
    r = _apply(client, a, cid, b, admin_id, accept_suggested=True)
    assert r.status_code == 200, r.text
    assert (r.json()["matched"], r.json()["suggested"]) == (2, 0)
    assert _cell(client, a, cid, desc, admin_id) == [recs[0]]
    assert _cell(client, a, cid, cont, admin_id) == [recs[1]]
    # nothing left waiting, so the conversion has no open exception list
    assert _exceptions(client, a, cid, admin_id).json()["open"] == 0


def test_an_unknown_tier_in_the_acceptance_is_refused(client, admin_id):
    """A client that posts a tier name nobody implements is a client whose
    acceptance means something other than it thinks, and silently accepting
    nothing would be the worst of the three possible answers."""
    a, b, cid, recs, desc, cont = _suggest_pair(client, admin_id, "td")
    r = _apply(client, a, cid, b, admin_id, accept_suggested=["descriptor", "nope"])
    assert r.status_code == 400, r.text
    assert "nope" in r.json()["detail"]
    assert _coldef(client, a, cid, admin_id)["type"] == "text", "refused and still wrote"


def test_accepting_one_row_links_every_record_it_was_proposed(client, admin_id):
    """Why the resolver needed an `accept` of its own rather than reusing
    item_id: a dropdown reading two values was proposed two records, and
    picking one of them by hand would quietly drop the other."""
    a = _board(client, admin_id, "מקור te")
    b = _board(client, admin_id, "לקוחות te")
    cid = _col(client, admin_id, a, type="dropdown", title="לקוחות",
               options=["אשדוד - עיריה", "ירוחם מועצה מקומית"])["id"]
    x1 = _item(client, admin_id, b, "אשדוד te")
    x2 = _item(client, admin_id, b, "ירוחם te")
    t = _item(client, admin_id, a, "שניים te", cid,
              ["אשדוד te - עיריה", "ירוחם te מועצה מקומית"])
    assert _apply(client, a, cid, b, admin_id, multiple=True).json()["suggested"] == 1

    r = _resolve(client, a, cid, t, admin_id, action="accept")
    assert r.status_code == 200, r.text
    assert sorted(_cell(client, a, cid, t, admin_id)) == sorted([x1, x2]), \
        "accepting the row dropped one of the records it was proposed"
    assert r.json()["closed"] is True


def test_accept_on_a_row_that_was_never_a_suggestion_is_refused(client, admin_id):
    a, b, cid, recs = _pair(client, admin_id, "tf", ["עיריית חיפה"])
    t = _item(client, admin_id, a, "חסר tf", cid, "קריית אונו")
    assert _apply(client, a, cid, b, admin_id).json()["unmatched"] == 1
    r = _resolve(client, a, cid, t, admin_id, action="accept")
    assert r.status_code == 400, r.text
    assert not _cell(client, a, cid, t, admin_id)


# ── turning it off ──────────────────────────────────────────────────────────

def test_asking_for_the_strict_rule_gets_exactly_the_strict_rule(client, admin_id):
    """`smart=false` is the wizard's own switch, and it has to reproduce
    yesterday's behaviour exactly — a preview computed under different
    settings is a preview of a different conversion."""
    a, b, cid, recs, desc, cont = _suggest_pair(client, admin_id, "tg")
    loose = _preview(client, a, cid, b, admin_id, smart=True).json()
    strict = _preview(client, a, cid, b, admin_id, smart=False).json()
    assert (loose["suggested"], loose["unmatched"]) == (2, 0)
    assert (strict["suggested"], strict["unmatched"]) == (0, 2)
    assert strict["smart"] is False and strict["smart_available"] is True
    assert all(r["reason"] == "no_match" for r in strict["exceptions"])


def test_a_deployment_can_switch_the_whole_ladder_off(client, admin_id,
                                                      monkeypatch):
    """The CITYOS_DUPLICATE_ITEM_LINKS pattern: an organisation whose boards
    are machine-generated wants tier 0 and nothing else, and would rather not
    have the option in the wizard at all. Asking for it does not get it."""
    a, b, cid, recs, desc, cont = _suggest_pair(client, admin_id, "th")
    monkeypatch.setenv("CITYOS_SMART_LINK_MATCH", "0")
    p = _preview(client, a, cid, b, admin_id, smart=True).json()
    assert p["smart"] is False, "the env var was overruled by the request"
    assert p["smart_available"] is False, "the wizard would still offer the switch"
    assert (p["matched"], p["suggested"], p["unmatched"]) == (0, 0, 2)

    r = _apply(client, a, cid, b, admin_id, smart=True, accept_suggested=True)
    assert r.status_code == 200, r.text
    assert r.json()["suggested"] == 0 and r.json()["unmatched"] == 2
    assert not _cell(client, a, cid, desc, admin_id)


# ── and the thing no tier may buy ───────────────────────────────────────────

def test_no_tier_reaches_a_record_the_actor_cannot_see(client, admin_id, guinea_id):
    """The one I would most want a test on. Every tier is a wider net over the
    SAME population, and a looser rule that reached further than the strict
    one would turn the whole ladder into the oracle the column-permission fix
    closed — worse, because `contains` answers on a fragment of a value.

    Neither a match, nor a suggestion, nor a candidate in the ambiguity.
    """
    # two records sharing no word, so each cell reaches exactly one of them —
    # the point here is the gate, not the arithmetic of the ladder
    a, b, cid, recs = _pair(client, admin_id, "ti", ["אשדוד", "מרכז הספורט"])
    for bid, role in ((a, "admin"), (b, "editor")):
        assert client.post(f"/api/boards/{bid}/members",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "role": role}).status_code == 200
    for hidden in recs:
        assert client.post(f"/api/tasks/{hidden}/permissions",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "perm": "none"}).status_code == 200
    desc = _item(client, admin_id, a, "תיאור ti", cid, "אשדוד - עיריה")
    cont = _item(client, admin_id, a, "הכלה ti", cid, "מרכז הספורט העירוני")

    mine = _preview(client, a, cid, b, admin_id, **SMART).json()
    theirs = _preview(client, a, cid, b, guinea_id, **SMART).json()
    # for the admin both tiers answer
    assert mine["suggested"] == 2, mine
    assert {r["tier"] for r in mine["suggestions"]} == {"descriptor", "contains"}
    # for guinea the records do not exist, at any tier
    assert (theirs["matched"], theirs["suggested"], theirs["ambiguous"]) == (0, 0, 0)
    assert theirs["unmatched"] == 2, theirs
    for t in (desc, cont):
        assert _tier_of(theirs, "suggestions", t) is None
        assert _tier_of(theirs, "exceptions", t)["candidates"] == [], \
            "a hidden record was named as a candidate"
    # and the counts the fields endpoint hands out do not leak them either
    assert _apply(client, a, cid, b, guinea_id, accept_suggested=True
                  ).json()["matched"] == 0
    for t in (desc, cont):
        assert not _cell(client, a, cid, t, admin_id)


def test_a_suggestion_accepted_by_a_second_admin_is_filtered_for_them(
        client, admin_id, guinea_id):
    """The proposal was worked out from what the admin who RAN the conversion
    could see; the person accepting it is a different reader, and their own
    visibility is what decides."""
    a, b, cid, recs = _pair(client, admin_id, "tj", ["אשדוד"])
    t = _item(client, admin_id, a, "תיאור tj", cid, "אשדוד - עיריה")
    for bid, role in ((a, "admin"), (b, "editor")):
        assert client.post(f"/api/boards/{bid}/members",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "role": role}).status_code == 200
    assert _apply(client, a, cid, b, admin_id).json()["suggested"] == 1
    assert client.post(f"/api/tasks/{recs[0]}/permissions",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "perm": "none"}).status_code == 200

    r = _resolve(client, a, cid, t, guinea_id, action="accept")
    assert r.status_code == 400, r.text
    assert not _cell(client, a, cid, t, admin_id)
    # the admin who can see it still can
    assert _resolve(client, a, cid, t, admin_id, action="accept").status_code == 200
    assert _cell(client, a, cid, t, admin_id) == [recs[0]]


# ── and everything round 1 promised still holds with the ladder on ──────────

def test_the_ladder_creates_no_record_and_keeps_every_original(client, admin_id):
    """The two promises that must survive every loosening of the rule."""
    a, b, cid, recs, desc, cont = _suggest_pair(client, admin_id, "tk")
    before = _record_ids(client, b, admin_id)
    assert _apply(client, a, cid, b, admin_id, accept_suggested=True
                  ).json()["matched"] == 2
    assert _record_ids(client, b, admin_id) == before, "a tier invented a record"

    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 200, r.text
    assert _cell(client, a, cid, desc, admin_id) == "אשדוד - עיריה"
    assert _cell(client, a, cid, cont, admin_id) == "נמל חדש גדול"
    assert _coldef(client, a, cid, admin_id)["type"] == "text"


def test_a_suggestion_accepted_by_hand_still_disarms_the_undo_if_it_is_edited(
        client, admin_id):
    """The drift guard counts an accepted suggestion as the conversion's own
    work, and an edit after it as somebody else's."""
    a, b, cid, recs, desc, cont = _suggest_pair(client, admin_id, "tl")
    assert _apply(client, a, cid, b, admin_id, accept_suggested=True).status_code == 200
    assert _revert(client, a, cid, admin_id).status_code == 200

    # again, and this time somebody moves one of the accepted links
    a, b, cid, recs, desc, cont = _suggest_pair(client, admin_id, "tm")
    assert _apply(client, a, cid, b, admin_id, accept_suggested=True).status_code == 200
    assert client.patch(f"/api/tasks/{desc}", json={"user_id": admin_id,
                                                    "custom_fields": {cid: [recs[1]]}}
                        ).status_code == 200
    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 400, r.text
    assert _cell(client, a, cid, desc, admin_id) == [recs[1]]


# ════════════════════════════════════════════════════════════════════════════
# ROUND 3 — a second identity, a split in the loosest tier, and what the chip
#           actually reads
#
# Three things the real board asked for once the ladder was on it:
#
#   · a FALLBACK match field. "שם לקוח מלא" carries the source's own format
#     and is blank on 144 of 500 records, whose own name covers them. One
#     spare, not a chain: "identify a customer by its full name, or by its
#     name if it has no full name" is a sentence an admin can check against
#     the board in front of them.
#   · `truncated`, split out of `contains` by what is LEFT OVER. The source
#     dropdown cut its options at 22 characters, so 'שדות נגב - מועצה אזורי'
#     is a town with half a descriptor on the end — which cannot change which
#     body is named. A leftover that is a real WORD can: 'החברה העירונית
#     אשקלון' is not 'אשקלון'. One tier is ticked by default and the other is
#     not, and the boundary between them is the whole safety of the default.
#   · a DISPLAY field. The record is called "בית דגן" and what everybody says
#     is "בית דגן - מועצה מקומית". Display only — nothing about matching,
#     writing or reverting knows it exists — but it is read by every person
#     who can open the source board, off a column on ANOTHER board, so it is
#     a permission surface in a way the match field never was.
# ════════════════════════════════════════════════════════════════════════════

def _full_name_board(client, admin_id, tag, records):
    """A target board with a "שם מלא" column, and `records` as
    [(title, full_name_or_None), …]. Returns (board, col_id, {title: id})."""
    b = _board(client, admin_id, f"לקוחות {tag}")
    full = _col(client, admin_id, b, type="text", title="שם מלא")["id"]
    ids = {}
    for title, value in records:
        ids[title] = _item(client, admin_id, b, title, full, value)
    return b, full, ids


# ── the fallback match field ───────────────────────────────────────────────

def test_a_record_is_indexed_under_the_first_field_it_fills_and_not_all_of_them(
        client, admin_id):
    """The mechanism, and it is a security-shaped choice rather than a tidy one.

    Indexing a record under every field it fills would let it answer to a name
    its admin chose not to identify it by — and would manufacture ambiguity
    out of fields nobody asked to match on. So the chain is read in order and
    stops at the first field that says anything.
    """
    a = _board(client, admin_id, "מקור r1")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    b, full, recs = _full_name_board(client, admin_id, "r1", [
        ("יבנה", "מי יבנה בעמ"),      # fills the primary — indexed ONLY by it
        ("אשדוד", None)])             # leaves it blank — falls back to its title
    by_primary = _item(client, admin_id, a, "לפי מלא r1", cid, "מי יבנה בעמ")
    by_title = _item(client, admin_id, a, "לפי שם r1", cid, "יבנה")
    by_spare = _item(client, admin_id, a, "לפי גיבוי r1", cid, "אשדוד")

    p = _preview(client, a, cid, b, admin_id, match_field=full,
                 fallback="title", smart=False).json()
    assert p["match_field_fallback"] == "title"
    assert (p["matched"], p["unmatched"]) == (2, 1), p
    got = {r["task_id"]: r["after"]["title"] for r in p["samples"]}
    assert got[by_primary] == "יבנה", "the primary field did not answer"
    assert got[by_spare] == "אשדוד", "the record with a blank primary never fell back"
    # the record that DID fill its primary is not also findable by its title —
    # that is the whole of "the first field it fills, not all of them"
    assert by_title not in got
    assert _by_task(p["exceptions"])[by_title]["reason"] == "no_match"


def test_the_fallback_buys_nothing_where_every_record_fills_the_primary(
        client, admin_id):
    """Measured on the real board: 436 exact matches with the primary alone
    and 436 with the fallback beside it. It is not a way to get more exact
    matches, and a test that let it look like one would be selling it wrong.
    """
    a = _board(client, admin_id, "מקור r2")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    b, full, recs = _full_name_board(client, admin_id, "r2", [
        ("יבנה", "יבנה"), ("אשדוד", "אשדוד"), ("חיפה", "חיפה")])
    for v in ("יבנה", "אשדוד", "אין כזה"):
        _item(client, admin_id, a, "src " + v + " r2", cid, v)

    alone = _preview(client, a, cid, b, admin_id, match_field=full, smart=False).json()
    spared = _preview(client, a, cid, b, admin_id, match_field=full,
                      fallback="title", smart=False).json()
    assert _counts(alone) == _counts(spared), (alone, spared)
    assert (alone["matched"], alone["unmatched"]) == (2, 1)


def test_the_fallback_replaces_a_confident_wrong_answer_with_the_right_record(
        client, admin_id):
    """Where its value actually is. A water company is not the town it is
    named after, and with only the full-name field indexed the company is not
    in the ladder at all — so the cell reaches past it to the town and
    proposes that, with every appearance of confidence. Put the company in
    the index and the same cell matches it outright.

    "A second identity does not only find more; it stops the first one being
    sure when it should not be."
    """
    a = _board(client, admin_id, "מקור r3")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    b, full, recs = _full_name_board(client, admin_id, "r3", [
        ("יבנה", "יבנה"),             # the town, with a full name
        ("מי יבנה בעמ", None)])       # the water company, without one
    t = _item(client, admin_id, a, "חברת מים r3", cid, 'מי יבנה בע"מ')

    alone = _preview(client, a, cid, b, admin_id, match_field=full).json()
    assert alone["suggested"] == 1 and alone["matched"] == 0
    wrong = alone["suggestions"][0]
    assert [c["title"] for c in wrong["candidates"]] == ["יבנה"], \
        "the fixture does not reproduce the wrong proposal"

    spared = _preview(client, a, cid, b, admin_id, match_field=full,
                      fallback="title").json()
    assert (spared["matched"], spared["suggested"]) == (1, 0), spared
    assert spared["samples"][0]["after"]["title"] == "מי יבנה בעמ"
    assert spared["samples"][0]["task_id"] == t


def test_no_fallback_is_exactly_the_behaviour_without_one(client, admin_id):
    a, b, cid, recs = _pair(client, admin_id, "r4", ["אשדוד"])
    t = _item(client, admin_id, a, "תיאור r4", cid, "אשדוד - עיריה")
    p = _preview(client, a, cid, b, admin_id).json()
    assert p["match_field_fallback"] in (None, "")
    assert (p["matched"], p["suggested"]) == (0, 1)


def test_the_fallback_is_stored_on_the_column_and_the_conversion(client, admin_id):
    a = _board(client, admin_id, "מקור r5")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    b, full, recs = _full_name_board(client, admin_id, "r5", [("אשדוד", None)])
    _item(client, admin_id, a, "src r5", cid, "אשדוד")

    r = _apply(client, a, cid, b, admin_id, match_field=full,
               match_field_fallback="title")
    assert r.status_code == 200, r.text
    assert r.json()["match_field_fallback"] == "title"
    assert _coldef(client, a, cid, admin_id)["connect"]["match_field_fallback"] == "title"


def test_a_fallback_field_the_actor_may_not_see_is_refused_like_the_primary(
        client, admin_id, guinea_id):
    """The spare goes through the same gate. A field somebody may not read the
    values of cannot become a second way for them to read them."""
    a = _board(client, admin_id, "מקור r6")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    b, full, recs = _full_name_board(client, admin_id, "r6", [("אשדוד", "אשדוד")])
    for bid, role in ((a, "admin"), (b, "editor")):
        assert client.post(f"/api/boards/{bid}/members",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "role": role}).status_code == 200
    assert client.post(f"/api/boards/{b}/columns/{full}/permissions",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "perm": "none"}).status_code == 200
    _item(client, admin_id, a, "src r6", cid, "אשדוד")

    denied = _preview(client, a, cid, b, guinea_id, match_field="title",
                      fallback=full)
    absent = _preview(client, a, cid, b, guinea_id, match_field="title",
                      fallback="col_nothing_at_all")
    assert denied.status_code == 404, denied.text
    assert denied.json() == absent.json()
    # and the board admin may still use it as the spare
    assert _preview(client, a, cid, b, admin_id, match_field="title",
                    fallback=full).status_code == 200


# ── truncated, split out of contains ───────────────────────────────────────

def test_the_five_known_wrong_containments_stay_out_of_the_ticked_tier(
        client, admin_id):
    """The test that protects the bulk-accept band.

    Every one of these is a DIFFERENT body from the record it reaches, and
    every one of them reaches it by containment. What keeps them out of the
    pre-ticked tier is that their leftover word is a real word — עירונית,
    כלכלית, מפעלי, הספורט — and not the visible stump of a descriptor. If one
    ever shows up as `truncated`, an admin pressing one button attaches the
    wrong customer to a project.

    Each is listed in BOTH spellings, and that is not padding. Three of the
    five as the user typed them carry the definite article — 'החברה', 'הח'' —
    and a descriptor list that handles עירייה but not העירייה never touches
    those. So a run of this test over the ה- forms alone proves nothing about
    the descriptor list at all: it was green through a mutation that added
    עירונית and כלכלית to it, because neither word was ever reached. The
    bare forms are what make this a guard-rail rather than a shape.
    """
    a, b, cid, recs = _pair(client, admin_id, "r7",
                            ["אשקלון", "בני שמעון", "עמנואל", "חיפה"])
    wrong = [
        # as the user typed them, definite article and all
        "החברה העירונית אשקלון", "חב' כלכלית אשקלון",
        "הח' הכלכל' מ.א בני שמעון", "מפעלי בית עמנואל",
        "קרית הספורט והחינוך חיפה",
        # and the same five bodies written without it, which is the coin flip
        # the other half of any hand-typed board lands on
        "חברה עירונית אשקלון", "חברה כלכלית אשקלון",
        "חברה כלכלית מ.א בני שמעון", "מפעלי עמנואל",
        "קרית ספורט וחינוך חיפה",
    ]
    ids = {v: _item(client, admin_id, a, "src " + v + " r7", cid, v) for v in wrong}

    p = _preview(client, a, cid, b, admin_id).json()
    by = {r["task_id"]: r for r in p["suggestions"]}
    for v in wrong:
        row = by.get(ids[v])
        assert row is not None, (v, p["exceptions"])
        assert row["tier"] == "contains", \
            f"{v} arrived in the tier an admin accepts in bulk"
    tiers = {t["key"]: t for t in p["tiers"]}
    assert tiers["contains"]["count"] == len(wrong)
    assert tiers["truncated"]["count"] == 0
    assert tiers["descriptor"]["count"] == 0, \
        "a company read as its town once the descriptors came off"
    # and the one that is ticked by default is not the one holding these
    assert tiers["contains"]["default_on"] is False
    assert tiers["truncated"]["default_on"] is True


def test_a_value_the_source_cut_short_is_a_truncation_and_is_ticked(
        client, admin_id):
    """The case the split exists for: the dropdown it came from stopped at 22
    characters, so what is left on the end is half a descriptor. A half
    descriptor cannot change which body is named."""
    a, b, cid, recs = _pair(client, admin_id, "r8", ["שדות נגב", "אשקלון"])
    cut_a = _item(client, admin_id, a, "חתוך א r8", cid, "שדות נגב - מועצה אזורי")
    cut_b = _item(client, admin_id, a, "חתוך ב r8", cid, "אשקלון - מועצה מקו")

    p = _preview(client, a, cid, b, admin_id).json()
    by = {r["task_id"]: r for r in p["suggestions"]}
    assert by[cut_a]["tier"] == "truncated", by[cut_a]
    assert [c["title"] for c in by[cut_a]["candidates"]] == ["שדות נגב"]
    assert by[cut_b]["tier"] == "truncated", by[cut_b]
    assert {t["key"]: t["count"] for t in p["tiers"]}["contains"] == 0


def test_a_leftover_shorter_than_three_characters_is_not_a_remnant(
        client, admin_id):
    """The threshold, pinned so nobody lowers it casually. At two, 'חב' would
    read as the visible start of חברה and 'החב' אשקלון' would arrive ticked —
    and 'מי' is a word, not a stump."""
    a, b, cid, recs = _pair(client, admin_id, "r9", ["אשקלון", "יבנה"])
    two = _item(client, admin_id, a, "שתיים r9", cid, "חב אשקלון")
    word = _item(client, admin_id, a, "מילה r9", cid, "מי יבנה")
    three = _item(client, admin_id, a, "שלוש r9", cid, "אשקלון מוע")

    p = _preview(client, a, cid, b, admin_id).json()
    by = {r["task_id"]: r for r in p["suggestions"]}
    assert by[two]["tier"] == "contains", \
        "a two-letter leftover was treated as a truncated descriptor"
    assert by[word]["tier"] == "contains", "'מי' is a word, not a stump"
    # and three characters of one is
    assert by[three]["tier"] == "truncated", by[three]


def test_a_truncation_on_the_targets_own_side_counts_too(client, admin_id):
    """The leftover is the difference between the two token sets, whichever
    side is the larger — the record's own name can be the cut one."""
    a, b, cid, recs = _pair(client, admin_id, "ra", ["שדות נגב - מועצה אזורי"])
    t = _item(client, admin_id, a, "מלא ra", cid, "שדות נגב")

    p = _preview(client, a, cid, b, admin_id).json()
    assert p["suggested"] == 1, p
    sug = p["suggestions"][0]
    assert sug["task_id"] == t and sug["tier"] == "truncated", sug
    assert [c["id"] for c in sug["candidates"]] == [recs[0]]


def test_accepting_truncations_leaves_the_containments_as_exceptions(
        client, admin_id):
    a, b, cid, recs = _pair(client, admin_id, "rb", ["שדות נגב", "אשקלון"])
    cut = _item(client, admin_id, a, "חתוך rb", cid, "שדות נגב - מועצה אזורי")
    other = _item(client, admin_id, a, "אחר rb", cid, "החברה העירונית אשקלון")

    r = _apply(client, a, cid, b, admin_id, accept_suggested=["truncated"])
    assert r.status_code == 200, r.text
    assert (r.json()["matched"], r.json()["suggested"]) == (1, 1)
    assert _cell(client, a, cid, cut, admin_id) == [recs[0]]
    assert not _cell(client, a, cid, other, admin_id)
    rows = _by_task(_exceptions(client, a, cid, admin_id).json()["rows"])
    assert list(rows) == [other]
    assert rows[other]["reason"] == "contains"


# ── display_field: what the chip reads ─────────────────────────────────────

def _display_board(client, admin_id, tag):
    """A converted column showing a "שם מלא" column of the target board, over
    three records: one with a value, one without, one whose value IS its
    title."""
    a = _board(client, admin_id, f"מקור {tag}")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    b = _board(client, admin_id, f"לקוחות {tag}")
    disp = _col(client, admin_id, b, type="text", title="שם מלא")["id"]
    has = _item(client, admin_id, b, "בית דגן " + tag, disp,
                "בית דגן - מועצה מקומית")
    none = _item(client, admin_id, b, "אשדוד " + tag, disp, None)
    same = _item(client, admin_id, b, "חיפה " + tag, disp, "חיפה " + tag)
    src = {}
    for title in ("בית דגן " + tag, "אשדוד " + tag, "חיפה " + tag):
        src[title] = _item(client, admin_id, a, "src " + title, cid, title)
    r = _apply(client, a, cid, b, admin_id, display_field=disp)
    assert r.status_code == 200, r.text
    return a, b, cid, disp, {"has": has, "none": none, "same": same}, src


def _link_display(client, bid, uid):
    return client.get(f"/api/boards/{bid}", headers=AS(uid)).json().get("link_display") or {}


def recs_by_title(client, bid, uid):
    return {t["title"]: t["id"] for t in _tasks(client, bid, uid).values()}


def test_a_connect_cell_can_read_a_field_of_the_linked_record(client, admin_id):
    """"בית דגן" is what the record is called and "בית דגן - מועצה מקומית" is
    what everybody says out loud."""
    a, b, cid, disp, recs, src = _display_board(client, admin_id, "rc")
    assert _coldef(client, a, cid, admin_id)["connect"]["display_field"] == disp
    shown = _link_display(client, a, admin_id)
    assert shown[cid][str(recs["has"])] == "בית דגן - מועצה מקומית"


def test_the_display_map_carries_only_what_differs_from_the_title(
        client, admin_id):
    """An override map, not a copy of every chip: the browser already resolves
    titles through /api/tasks/lookup. A record whose display text equals its
    title is ABSENT rather than present and equal — otherwise every board
    render would ship a second copy of every name it already sent."""
    a, b, cid, disp, recs, src = _display_board(client, admin_id, "rd")
    shown = _link_display(client, a, admin_id).get(cid, {})
    assert str(recs["has"]) in shown
    assert str(recs["same"]) not in shown, "a record reading as its own title was sent"
    assert str(recs["none"]) not in shown, "a record with no value was sent"


def test_a_record_with_no_value_in_the_display_field_still_reads_as_its_title(
        client, admin_id):
    """224 of 604 live records leave it empty, so this is the common case and
    not an edge. An empty chip reads as a broken link."""
    a, b, cid, disp, recs, src = _display_board(client, admin_id, "re")
    got = client.get(f"/api/tasks/lookup?ids={recs['none']}"
                     f"&board_id={a}&col_id={cid}", headers=AS(admin_id)).json()
    entry = got["items"][0]
    assert entry["display"] == entry["title"] == "אשדוד re"
    assert entry["display"], "the chip would have drawn blank"


def test_a_viewer_who_may_not_see_the_field_is_shown_the_title_instead(
        client, admin_id, guinea_id):
    """The gate is per viewer and at READ time. A match field is read once, by
    the one admin running a conversion; a display field is read by everybody
    who can open the source board, off a column on another board they may
    never have been given — and the admin's own sight of it when they chose it
    grants nothing.

    It falls back to the title rather than blanking: a blank chip reads as a
    broken link, and the word "מוסתר" would itself be the disclosure.
    """
    a, b, cid, disp, recs, src = _display_board(client, admin_id, "rf")
    for bid in (a, b):
        assert client.post(f"/api/boards/{bid}/members",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "role": "editor"}).status_code == 200
    # while they may read it, they see what the admin sees
    assert _link_display(client, a, guinea_id)[cid][str(recs["has"])] == \
        "בית דגן - מועצה מקומית"

    assert client.post(f"/api/boards/{b}/columns/{disp}/permissions",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "perm": "none"}).status_code == 200
    theirs = _link_display(client, a, guinea_id)
    assert theirs.get(cid, {}) == {}, theirs
    # the admin is unaffected — this is per viewer, not a column that broke
    assert _link_display(client, a, admin_id)[cid][str(recs["has"])] == \
        "בית דגן - מועצה מקומית"
    # and the chip still says something true: the title, which lookup has
    # always given them
    entry = client.get(f"/api/tasks/lookup?ids={recs['has']}"
                       f"&board_id={a}&col_id={cid}",
                       headers=AS(guinea_id)).json()["items"][0]
    assert entry["display"] == entry["title"] == "בית דגן rf"
    assert "מוסתר" not in str(entry)


def test_a_display_field_that_stops_existing_reads_as_the_title(client, admin_id):
    a, b, cid, disp, recs, src = _display_board(client, admin_id, "rg")
    assert _link_display(client, a, admin_id).get(cid)
    assert client.patch(f"/api/boards/{b}",
                        json={"user_id": admin_id, "columns": []}).status_code == 200
    assert _link_display(client, a, admin_id) == {}
    entry = client.get(f"/api/tasks/lookup?ids={recs['has']}"
                       f"&board_id={a}&col_id={cid}",
                       headers=AS(admin_id)).json()["items"][0]
    assert entry["display"] == entry["title"]


def test_lookup_without_a_column_answers_exactly_what_it_always_did(
        client, admin_id):
    """The parameters are optional and the old call is unchanged: `display` is
    the title, and every other field is what it was."""
    a, b, cid, disp, recs, src = _display_board(client, admin_id, "rh")
    bare = client.get(f"/api/tasks/lookup?ids={recs['has']}",
                      headers=AS(admin_id)).json()["items"][0]
    assert bare["title"] == "בית דגן rh"
    assert bare["display"] == bare["title"], \
        "a caller that named no column got a display field anyway"
    assert bare["board_id"] == b and bare["deleted"] is False


def test_the_display_field_changes_nothing_about_matching_or_the_undo(
        client, admin_id):
    """Links are stored by id. The field decides what a chip reads and nothing
    else — so the same conversion with and without one matches the same cells,
    and the revert puts the same board back."""
    a, b, cid, disp, recs, src = _display_board(client, admin_id, "ri")
    # every cell linked by title, which is the field the match ran on — the
    # display field took no part in it
    for title, tid in src.items():
        assert _cell(client, a, cid, tid, admin_id) == [recs_by_title(client, b,
                                                                     admin_id)[title]], title
    r = _revert(client, a, cid, admin_id)
    assert r.status_code == 200, r.text
    assert _coldef(client, a, cid, admin_id)["type"] == "text"
    for title, tid in src.items():
        assert _cell(client, a, cid, tid, admin_id) == title


def test_a_display_field_may_not_be_a_link_or_a_mirror(client, admin_id):
    """A chip showing a chip is its own feature and not this one."""
    a = _board(client, admin_id, "מקור rj")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    b = _board(client, admin_id, "לקוחות rj")
    made = _cols(client, admin_id, b, [
        {"type": "connect", "title": "קשר",
         "connect": {"board_ids": [a], "multiple": True, "two_way": False}},
        {"type": "text", "title": "שם מלא"}])
    conn = next(c["id"] for c in made if c["type"] == "connect")
    _item(client, admin_id, b, "רשומה rj")
    _item(client, admin_id, a, "src rj", cid, "רשומה rj")

    r = _apply(client, a, cid, b, admin_id, display_field=conn)
    assert r.status_code == 400, r.text
    assert "קישור" in r.json()["detail"]
    assert _coldef(client, a, cid, admin_id)["type"] == "text"


def test_a_display_field_the_admin_cannot_see_gets_the_same_404_a_missing_one_does(
        client, admin_id, guinea_id):
    """Same reasoning as the match field: a separate refusal for "it is there
    but not for you" is the confirmation an oracle wants."""
    a = _board(client, admin_id, "מקור rk")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    b = _board(client, admin_id, "לקוחות rk")
    secret = _col(client, admin_id, b, type="text", title="סודי")["id"]
    for bid, role in ((a, "admin"), (b, "editor")):
        assert client.post(f"/api/boards/{bid}/members",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "role": role}).status_code == 200
    assert client.post(f"/api/boards/{b}/columns/{secret}/permissions",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "perm": "none"}).status_code == 200
    _item(client, admin_id, b, "רשומה rk")
    _item(client, admin_id, a, "src rk", cid, "רשומה rk")

    denied = _apply(client, a, cid, b, guinea_id, display_field=secret)
    absent = _apply(client, a, cid, b, guinea_id, display_field="col_nothing")
    assert denied.status_code == 404, denied.text
    assert denied.json() == absent.json()
    assert _coldef(client, a, cid, admin_id)["type"] == "text"


# ════════════════════════════════════════════════════════════════════════════
# ROUND 4 — `abbrev`, the loosest rule in the feature and the most bounded
#
# The user asked for one thing: "חב' עירונית ראשון לציון צריך להתאים ל החברה
# העירונית ראשלצ". Two abbreviations in one value, and nothing above the
# ladder could do either — חב ↔ חברה is a contraction, and ראשלצ ↔ ראשון
# לציון is two words run together, which the acronym tier cannot produce
# (first letters give רל).
#
# One rule covers both: a token abbreviates a word when it is a PREFIX of it,
# and one token may stand for several consecutive words as their prefixes run
# together. What keeps it from being sloppy is that BOTH SIDES must be
# consumed entirely — that is the difference between this and containment,
# and it is what turns five plausible subsidiaries into one correct answer.
#
# And one bound that measurement forced. Over 1,285,606 real name pairs a
# bare prefix test admitted exactly three kinds of thing: the case above, and
# תמר↔תמרית and חב מודיעין↔חבל מודיעין, which are different places. So a
# token standing for a SINGLE word must be at most half of it. A token
# standing for several is self-evidently an abbreviation by its shape and is
# exempt, because the ratio would reject ראש|לצ.
# ════════════════════════════════════════════════════════════════════════════

def test_an_abbreviated_word_reaches_the_record_that_spells_it_out(
        client, admin_id):
    """The user's own request, both halves of it. Suggested, never linked."""
    a, b, cid, recs = _pair(client, admin_id, "v1", ["חברה עירונית ראשון לציון"])
    short = _item(client, admin_id, a, "מקוצר v1", cid, "חב' עירונית ראשון לציון")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert (p["matched"], p["suggested"]) == (0, 1), p
    sug = _tier_of(p, "suggestions", short)
    assert sug["tier"] == "abbrev"
    assert [c["id"] for c in sug["candidates"]] == [recs[0]]

    # and the apply writes nothing without being told to accept it
    assert _apply(client, a, cid, b, admin_id).json()["suggested"] == 1
    assert not _cell(client, a, cid, short, admin_id)


def test_one_token_may_stand_for_several_words_run_together(client, admin_id):
    """ראשלצ is ראש|לצ. The acronym tier cannot reach it — first letters give
    רל — and this is the whole reason the rule is prefix-based rather than
    initial-based."""
    a, b, cid, recs = _pair(client, admin_id, "v2", ["חברה עירונית ראשלצ"])
    t = _item(client, admin_id, a, "מלא v2", cid, "חברה עירונית ראשון לציון")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    sug = _tier_of(p, "suggestions", t)
    assert sug is not None and sug["tier"] == "abbrev", p
    assert [c["id"] for c in sug["candidates"]] == [recs[0]]


def test_both_sides_must_be_consumed_so_a_subsidiary_is_not_reached(
        client, admin_id):
    """The property that turns five plausible candidates into one answer.

    The board holds the company and three of its subsidiaries, every one of
    them starting with the same three words. Containment would reach all four
    — and a rule that shrugged off the extra words would be picking one
    subsidiary out of five at random. Every word on each side has to be
    answered by a word on the other, so only the one that says exactly what
    the cell says is a candidate at all.
    """
    a, b, cid, recs = _pair(client, admin_id, "v3", [
        "חברה עירונית ראשון לציון",
        "חברה עירונית ראשון לציון לבטחון וסדר ציבורי",
        "חברה עירונית ראשון לציון לתרבות הפנאי",
        "חברה כלכלית ראשון לציון"])
    t = _item(client, admin_id, a, "מקוצר v3", cid, "חב' עירונית ראשון לציון")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert p["ambiguous"] == 0, "the subsidiaries were reached and made it a tie"
    sug = _tier_of(p, "suggestions", t)
    assert sug["tier"] == "abbrev", sug
    assert [c["id"] for c in sug["candidates"]] == [recs[0]], \
        [c["title"] for c in sug["candidates"]]


def test_a_shorter_word_that_merely_starts_the_same_is_not_an_abbreviation(
        client, admin_id):
    """The bound measurement forced, and the one keeping the loosest rule in
    the feature honest. תמר is not תמרית and חב מודיעין is not חבל מודיעין —
    they are different places, and a bare prefix test called them the same.

    A token standing for ONE word must be at most half of it: חב (2) of חברה
    (4) passes, תמר (3) of תמרית (5) and חב (2) of חבל (3) do not.
    """
    a, b, cid, recs = _pair(client, admin_id, "v4",
                            ["תמרית", "חבל מודיעין", "חברה עירונית נס ציונה"])
    too_long = _item(client, admin_id, a, "תמר v4", cid, "תמר")
    too_close = _item(client, admin_id, a, "חבל v4", cid, "חב מודיעין")
    real = _item(client, admin_id, a, "חברה v4", cid, "חב' עירונית נס ציונה")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert p["suggested"] == 1, p
    assert _tier_of(p, "suggestions", real)["tier"] == "abbrev"
    for t, why in ((too_long, "תמר is 3 of 5 — over half of תמרית"),
                   (too_close, "חב is 2 of 3 — over half of חבל")):
        assert _tier_of(p, "suggestions", t) is None, why
        assert _tier_of(p, "exceptions", t)["reason"] == "no_match", why


def test_a_run_together_abbreviation_is_exempt_from_the_half_rule(
        client, admin_id):
    """ראש is three letters of ראשון's five — over half, and rejected if the
    one-word ratio applied. A token standing for several words is
    self-evidently an abbreviation by its shape, so the ratio is not asked."""
    a, b, cid, recs = _pair(client, admin_id, "v5", ["ראשון לציון"])
    t = _item(client, admin_id, a, "מקוצר v5", cid, "ראשלצ")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    sug = _tier_of(p, "suggestions", t)
    assert sug is not None and sug["tier"] == "abbrev", p
    assert [c["id"] for c in sug["candidates"]] == [recs[0]]
    # and the same three letters alone, against the same word, are not — that
    # is the one-word ratio still doing its job beside the exemption
    a2, b2, cid2, recs2 = _pair(client, admin_id, "v5b", ["ראשון"])
    t2 = _item(client, admin_id, a2, "חלקי v5b", cid2, "ראש")
    p2 = _preview(client, a2, cid2, b2, admin_id, **SMART).json()
    assert _tier_of(p2, "suggestions", t2) is None, p2["suggestions"]


def test_a_value_reachable_by_both_truncation_and_abbreviation_is_a_truncation(
        client, admin_id):
    """The walk is ordered by tightness and `truncated` is asked first.

    Placed naively before containment, `abbrev` took six rows off `truncated`
    — the same answers, demoted out of the band an admin ticks by default.
    'שדות נגב - מועצה אזו' aligns as an abbreviation (אזו of אזורית is three
    of seven) and is also a record plus a cut-off descriptor, and the second
    is the tighter and more trustworthy description of it.
    """
    a, b, cid, recs = _pair(client, admin_id, "v6", ["שדות נגב - מועצה אזורית"])
    t = _item(client, admin_id, a, "חתוך v6", cid, "שדות נגב - מועצה אזו")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    sug = _tier_of(p, "suggestions", t)
    assert sug["tier"] == "truncated", \
        "an abbreviation demoted a truncation out of the default-tick band"
    tiers = {x["key"]: x for x in p["tiers"]}
    assert tiers["abbrev"]["count"] == 0 and tiers["truncated"]["count"] == 1


def test_a_doubled_space_in_the_record_does_not_hide_it(client, admin_id):
    """The record on the live board is spelled with two spaces in the middle.
    The whitespace collapse already handles it — pinned because this is how a
    candidate goes silently invisible and nobody can see why."""
    a, b, cid, recs = _pair(client, admin_id, "v7", ["חברה  עירונית ראשלצ"])
    t = _item(client, admin_id, a, "מלא v7", cid, "חברה עירונית ראשון לציון")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    sug = _tier_of(p, "suggestions", t)
    assert sug is not None, "the doubled space hid the record"
    assert sug["tier"] == "abbrev"
    assert [c["id"] for c in sug["candidates"]] == [recs[0]]


def test_abbreviations_do_not_arrive_ticked(client, admin_id):
    """Suggest-only and NOT in the default-tick band. Its entire
    true-positive evidence base is one value, which is not enough to put it in
    front of an admin pre-agreed to."""
    a, b, cid, recs = _pair(client, admin_id, "v8",
                            ["חברה עירונית נס ציונה", "שדות נגב"])
    ab = _item(client, admin_id, a, "מקוצר v8", cid, "חב' עירונית נס ציונה")
    tr = _item(client, admin_id, a, "חתוך v8", cid, "שדות נגב - מועצה אזורי")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    tiers = {x["key"]: x for x in p["tiers"]}
    assert tiers["abbrev"]["default_on"] is False, \
        "abbreviation arrives pre-agreed on one value's worth of evidence"
    assert tiers["abbrev"]["auto"] is False, "an abbreviation linked itself"
    assert tiers["truncated"]["default_on"] is True

    # the tiers an admin would arrive with ticked leave the abbreviation alone
    r = _apply(client, a, cid, b, admin_id,
               accept_suggested=[k for k, v in tiers.items() if v["default_on"]])
    assert r.status_code == 200, r.text
    assert (r.json()["matched"], r.json()["suggested"]) == (1, 1)
    assert _cell(client, a, cid, tr, admin_id) == [recs[1]]
    assert not _cell(client, a, cid, ab, admin_id)
    rows = _by_task(_exceptions(client, a, cid, admin_id).json()["rows"])
    assert list(rows) == [ab] and rows[ab]["reason"] == "abbrev"


def test_accepting_abbreviations_links_them(client, admin_id):
    a, b, cid, recs = _pair(client, admin_id, "v9",
                            ["חברה עירונית נס ציונה", "שדות נגב"])
    ab = _item(client, admin_id, a, "מקוצר v9", cid, "חב' עירונית נס ציונה")
    tr = _item(client, admin_id, a, "חתוך v9", cid, "שדות נגב - מועצה אזורי")

    r = _apply(client, a, cid, b, admin_id, accept_suggested=["abbrev"])
    assert r.status_code == 200, r.text
    assert (r.json()["matched"], r.json()["suggested"]) == (1, 1)
    assert _cell(client, a, cid, ab, admin_id) == [recs[0]]
    assert not _cell(client, a, cid, tr, admin_id), "a tier nobody accepted was linked"


def test_the_abbreviation_only_reaches_her_board_with_the_fallback_on(
        client, admin_id):
    """The two features are one fix on the configuration actually in use.

    On her board the company's "שם לקוח מלא" is empty, so with the primary
    field alone the record is not in the index at any tier — and the cell
    reaches past it to the TOWN and proposes that, which is the wrong
    customer with every appearance of confidence. Turn the fallback on, the
    company enters the index under its own name, and the same cell resolves
    to it by abbreviation.

    This is the second independent argument for the fallback: it does not
    only find more, it stops a looser tier being sure about the wrong thing.
    """
    a = _board(client, admin_id, "מקור va")
    cid = _col(client, admin_id, a, type="text", title="לקוחות")["id"]
    b, full, recs = _full_name_board(client, admin_id, "va", [
        ("ראשון לציון", "ראשון לציון"),          # the town, with a full name
        ("חברה עירונית ראשון לציון", None)])     # the company, without one
    t = _item(client, admin_id, a, "מקוצר va", cid, "חב' עירונית ראשון לציון")

    alone = _preview(client, a, cid, b, admin_id, match_field=full).json()
    wrong = _tier_of(alone, "suggestions", t)
    assert wrong["tier"] == "contains", alone
    assert [c["title"] for c in wrong["candidates"]] == ["ראשון לציון"], \
        "the fixture no longer reproduces the wrong proposal"

    spared = _preview(client, a, cid, b, admin_id, match_field=full,
                      fallback="title").json()
    right = _tier_of(spared, "suggestions", t)
    assert right["tier"] == "abbrev", spared
    assert [c["title"] for c in right["candidates"]] == \
        ["חברה עירונית ראשון לציון"]


def test_an_abbreviation_reaching_two_records_is_an_ambiguity(client, admin_id):
    """The one-candidate rule holds here as everywhere: a tier that answers
    twice reports both and chooses neither."""
    a, b, cid, recs = _pair(client, admin_id, "vb",
                            ["חברה עירונית נס ציונה", "חברת עירונית נס ציונה"])
    t = _item(client, admin_id, a, "מקוצר vb", cid, "חב' עירונית נס ציונה")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert (p["matched"], p["suggested"]) == (0, 0), p
    exc = _tier_of(p, "exceptions", t)
    assert exc["outcome"] == "ambiguous" and exc["reason"] == "several"
    assert sorted(c["id"] for c in exc["candidates"]) == sorted(recs)
    assert _apply(client, a, cid, b, admin_id, accept_suggested=True).status_code == 200
    assert not _cell(client, a, cid, t, admin_id)


def test_no_tier_including_abbreviation_reaches_a_hidden_record(
        client, admin_id, guinea_id):
    """The invariant every tier has had to satisfy since the ladder landed,
    asked once more of the newest and loosest one."""
    a, b, cid, recs = _pair(client, admin_id, "vc", ["חברה עירונית נס ציונה"])
    for bid, role in ((a, "admin"), (b, "editor")):
        assert client.post(f"/api/boards/{bid}/members",
                           json={"actor_id": admin_id, "user_id": guinea_id,
                                 "role": role}).status_code == 200
    assert client.post(f"/api/tasks/{recs[0]}/permissions",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "perm": "none"}).status_code == 200
    t = _item(client, admin_id, a, "מקוצר vc", cid, "חב' עירונית נס ציונה")

    assert _preview(client, a, cid, b, admin_id, **SMART).json()["suggested"] == 1
    theirs = _preview(client, a, cid, b, guinea_id, **SMART).json()
    assert (theirs["matched"], theirs["suggested"], theirs["ambiguous"]) == (0, 0, 0)
    assert _tier_of(theirs, "exceptions", t)["candidates"] == []


def test_every_tier_the_server_walks_has_a_name_and_a_place_in_the_order(
        client, admin_id):
    """The ladder is a list the preview hands out, and a tier the server can
    answer with but the dialog has no word for would render as a bare key.
    Ordered loosest-last, because the order IS the rule: a tier may only ever
    be overruled by a tighter one."""
    a, b, cid, recs = _pair(client, admin_id, "vd", ["אשדוד"])
    _item(client, admin_id, a, "src vd", cid, "אשדוד")
    p = _preview(client, a, cid, b, admin_id, **SMART).json()

    keys = [x["key"] for x in p["tiers"]]
    assert keys == ["exact", "punct", "spelling", "descriptor", "acronym",
                    "truncated", "abbrev", "contains"], keys
    assert [x["key"] for x in p["tiers"] if x["auto"]] == ["exact", "punct"]
    assert [x["key"] for x in p["tiers"] if x["default_on"]] == \
        ["descriptor", "truncated"]
    for x in p["tiers"]:
        assert x["label"] and not x["label"].startswith("col_"), x
    # the three a person is asked to judge say why, beyond their name
    assert {x["key"] for x in p["tiers"] if x.get("note")} == \
        {"truncated", "abbrev", "contains"}


# ════════════════════════════════════════════════════════════════════════════
# ROUND 5 — what a mutation review found the fixtures were not reaching
#
# Five of six mutations were caught. The sixth was the one that matters most:
# adding עירונית and כלכלית to _ORG_DESCRIPTORS, the exact change the whole
# guard-rail exists to prevent, left the file green. Not because the
# assertions were wrong — because the FIXTURES never reached the code they
# assert about. Three of the five known-wrong values carry the definite
# article, _ORG_DESCRIPTORS handled עירייה and not העירייה, so neither
# spelling of the added words was ever stripped and nothing moved.
#
# A test that reads like a guard-rail and never executes the path it guards
# is worse than no test, because it is counted. Hence this section: both
# spellings of every descriptor, and the three stop-on-two holes the same
# review turned up beside it.
# ════════════════════════════════════════════════════════════════════════════

_DESCRIPTOR_WORDS = ["עירייה", "עיריה", "עיריית", "עירית", "מועצה", "מקומית",
                     "אזורית", "רשות", "ועד", "חברת", "חברה", "עמותת",
                     "עמותה", "איגוד", "מנהלת"]


def test_every_descriptor_is_stripped_with_and_without_the_definite_article(
        client, admin_id):
    """'אשדוד העירייה' is written as often as 'אשדוד עירייה', and a list that
    holds only the bare form silently misses half a hand-typed board — those
    cells fell to `contains`, out of the band an admin ticks, so the feature
    simply did less than it said for no reason anybody could see.

    Both spellings of all fifteen, in one preview. The loop is the point: a
    descriptor added later without its ה- form fails here rather than in six
    months on somebody's board.
    """
    a, b, cid, recs = _pair(client, admin_id, "w1", ["אשדוד"])
    cells = ([f"אשדוד {w}" for w in _DESCRIPTOR_WORDS]
             + [f"אשדוד ה{w}" for w in _DESCRIPTOR_WORDS])
    ids = {v: _item(client, admin_id, a, f"src {v} w1", cid, v) for v in cells}

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert p["suggested"] == len(cells), p
    by = {r["task_id"]: r for r in p["suggestions"]}
    for v in cells:
        row = by.get(ids[v])
        assert row is not None, (v, p["exceptions"])
        assert row["tier"] == "descriptor", \
            f"{v!r} missed the descriptor tier and fell to {row['tier']}"
        assert [c["id"] for c in row["candidates"]] == [recs[0]], v
    assert {t["key"]: t["count"] for t in p["tiers"]}["contains"] == 0


def test_the_definite_article_is_stripped_on_the_records_side_too(
        client, admin_id):
    """Both sides go through _descriptor_key, so the board may be the one
    writing it out in full."""
    a, b, cid, recs = _pair(client, admin_id, "w2", ["אשדוד העירייה", "חדרה"])
    bare = _item(client, admin_id, a, "חשוף w2", cid, "אשדוד")
    dressed = _item(client, admin_id, a, "מלא w2", cid, "חדרה המועצה")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    by = {r["task_id"]: r for r in p["suggestions"]}
    assert by[bare]["tier"] == "descriptor"
    assert [c["id"] for c in by[bare]["candidates"]] == [recs[0]]
    assert by[dressed]["tier"] == "descriptor"
    assert [c["id"] for c in by[dressed]["candidates"]] == [recs[1]]


def test_two_containment_candidates_stop_the_walk_whatever_either_is_called(
        client, admin_id):
    """`truncated` is a LABEL on containment's own candidates, not a search of
    its own — so filtering the candidate list down to its single `truncated`
    member and returning that is the tier contradicting its own search.

    A board holding אשקלון beside אשקלון אזורי מפעלים answered the cell
    "אשקלון מועצה אזורי" with אשקלון alone, on the tier that arrives TICKED,
    and the admin never saw the second. X beside X-plus-two-words is the
    commonest shape on a customers board.
    """
    a, b, cid, recs = _pair(client, admin_id, "w3",
                            ["אשקלון", "אשקלון אזורי מפעלים"])
    t = _item(client, admin_id, a, "שתיים w3", cid, "אשקלון מועצה אזורי")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert (p["matched"], p["suggested"]) == (0, 0), p
    exc = _tier_of(p, "exceptions", t)
    assert (exc["outcome"], exc["reason"]) == ("ambiguous", "several"), exc
    assert sorted(c["id"] for c in exc["candidates"]) == sorted(recs), \
        "one of the two was dropped from the list a person has to choose from"
    # and nothing arrives ticked out of it
    assert {x["key"]: x["count"] for x in p["tiers"]}["truncated"] == 0
    assert _apply(client, a, cid, b, admin_id,
                  accept_suggested=True).status_code == 200
    assert not _cell(client, a, cid, t, admin_id)


def test_an_abbreviation_with_one_answer_may_still_resolve_a_containment_tie(
        client, admin_id):
    """And the line the fix above does NOT cross, which is worth pinning as
    carefully as the fix itself.

    `abbrev` is a different predicate over the whole board with a candidate
    set of its own, not a relabelling of containment's hits: "חב' עירונית נס
    ציונה" is two records by containment — the town and its company — and
    exactly one by alignment, because only one of them says the same words.
    A tighter question with a unique answer is not a tie broken by a looser
    rule. (If this is ever reconsidered, the thing to weigh is that the
    containment pair here is town-plus-company, the exact shape every
    measured wrong proposal has.)
    """
    a, b, cid, recs = _pair(client, admin_id, "w4",
                            ["נס ציונה", "חברה עירונית נס ציונה"])
    t = _item(client, admin_id, a, "מקוצר w4", cid, "חב' עירונית נס ציונה")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    sug = _tier_of(p, "suggestions", t)
    assert sug is not None and sug["tier"] == "abbrev", p
    assert [c["id"] for c in sug["candidates"]] == [recs[1]], \
        "the alignment did not pick the company"
    # and it is unticked, so nothing is written without somebody saying so
    assert {x["key"]: x["default_on"] for x in p["tiers"]}["abbrev"] is False


def test_an_abbreviation_that_answers_twice_is_an_ambiguity_like_any_other(
        client, admin_id):
    a, b, cid, recs = _pair(client, admin_id, "w5",
                            ["חברה עירונית נס ציונה", "חברת עירונית נס ציונה"])
    t = _item(client, admin_id, a, "מקוצר w5", cid, "חב' עירונית נס ציונה")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    assert (p["matched"], p["suggested"]) == (0, 0), p
    exc = _tier_of(p, "exceptions", t)
    assert (exc["outcome"], exc["reason"]) == ("ambiguous", "several")
    assert sorted(c["id"] for c in exc["candidates"]) == sorted(recs)


def test_a_leftover_that_is_an_ordinary_word_is_not_a_descriptor_stump(
        client, admin_id):
    """Length alone cannot tell a cut-off descriptor from a word. חבר is
    three letters of חברה and is also "member"; מנהל is four of מנהלת and is
    also "manager"; אזור is the start of אזורית and is also a town near Holon
    that is on the live customers board — which is exactly the collision the
    ticked tier must not make.

    They were all qualifying as remnants, so 'עמנואל חבר' arrived pre-agreed
    as 'עמנואל'. A list, not a heuristic, because this is the band whose
    proposals an admin accepts without reading.
    """
    a, b, cid, recs = _pair(client, admin_id, "w6",
                            ["עמנואל", "מודיעין", "להבים", "שדות נגב"])
    words = {"חבר": "עמנואל", "מנהל": "מודיעין", "אזור": "להבים"}
    ids = {w: _item(client, admin_id, a, f"src {w} w6", cid, f"{town} {w}")
           for w, town in words.items()}
    stump = _item(client, admin_id, a, "גדם w6", cid, "שדות נגב מועצה אזו")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    by = {r["task_id"]: r for r in p["suggestions"]}
    for w in words:
        assert by[ids[w]]["tier"] == "contains", \
            f"{w!r} was read as a cut-off descriptor and arrived ticked"
    # and a real stump still is one, so the deny-list has not blunted the tier
    assert by[stump]["tier"] == "truncated", by[stump]
    tiers = {x["key"]: x["count"] for x in p["tiers"]}
    assert (tiers["contains"], tiers["truncated"]) == (len(words), 1)


def test_the_guard_rail_catches_the_descriptor_list_growing(client, admin_id):
    """A standing instruction to whoever touches _ORG_DESCRIPTORS, written as
    a test rather than a comment.

    Both of the shapes that must break are here: a company whose only
    distinguishing word is עירונית, and one whose only distinguishing word is
    כלכלית. Each reaches its town by containment today. Add either word to
    the descriptor list and that becomes a `descriptor` match — the band an
    admin accepts four hundred of in one click — and this test goes red,
    which is the entire point of it.
    """
    a, b, cid, recs = _pair(client, admin_id, "w7", ["ראשון לציון", "אשקלון"])
    urban = _item(client, admin_id, a, "עירונית w7", cid, "חברה עירונית ראשון לציון")
    econ = _item(client, admin_id, a, "כלכלית w7", cid, "חברה כלכלית אשקלון")

    p = _preview(client, a, cid, b, admin_id, **SMART).json()
    by = {r["task_id"]: r for r in p["suggestions"]}
    for t, word in ((urban, "עירונית"), (econ, "כלכלית")):
        assert by[t]["tier"] == "contains", \
            f"{word} has been made a descriptor — a company now reads as its town"
    assert {x["key"]: x["count"] for x in p["tiers"]}["descriptor"] == 0
    assert p["matched"] == 0


# ════════════════════════════════════════════════════════════════════════════
# the browser's half
# ════════════════════════════════════════════════════════════════════════════

def test_the_harness_renders_every_kind_of_row_the_server_can_send():
    """The root cause of a bug report, pinned so it cannot recur.

    tests/frontend/column_to_link_wizard.mjs drives the exception resolver off
    a fixture, and that fixture held an `unmatched` row and an `ambiguous` row
    and nothing else — so the blue suggestion row, the "אשר" button and
    LinkMatch.accept were never rendered by any test while the file read as
    covering step 3. A user reported "אשר does nothing" and there was no test
    to consult either way.

    The fixture is a copy of a server response, and a copy drifts. This is the
    cheap check that it has not: every outcome link-exceptions can put in a
    row has to appear in it, so adding a fourth to the server fails here
    rather than six months later in somebody's browser.
    """
    src = HARNESS.read_text(encoding="utf-8")
    fixture = src[src.index("const EXCEPTIONS"):src.index("/* ---- the sandbox ----")]
    for outcome in cityos_main.CONVERSION_EXCEPTIONS:
        assert f"outcome:'{outcome}'" in fixture, \
            f"the harness never renders a {outcome!r} row — it cannot have been tested"
    # and the reason a suggestion row carries is a tier, which is what the row
    # shows instead of a failure message
    assert "tier_he:" in fixture, "a suggestion with no tier name renders a blank label"


def test_the_wizard_and_the_pending_cell_behave():
    """Driven harness: tests/frontend/column_to_link_wizard.mjs.

    Three steps that chain, the entry into them from the column menu, the
    "טיפול בחריגות" entry on a column mid-conversion, and the cell that shows
    its original text instead of drawing empty.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_browser_asks_for_the_preview_with_the_cardinality_it_is_about_to_apply():
    """The single/multi switch feeds the preview call. Omit `multiple` and
    too_many_values counts as zero on the screen and not in the write, which is
    the one way step two and step three can disagree."""
    src = INDEX.read_text(encoding="utf-8")
    i = src.find("link-match?")
    assert i > 0, "nothing in the browser asks for the conversion preview"
    call = src[i:i + 400]
    assert "multiple=" in call, call[:200]


def test_the_wizard_writes_only_from_its_own_confirm_button():
    """Opening the wizard must not convert anything: the preview is the thing
    somebody agrees to, and an entry that wrote on the way in would mean there
    was never anything to agree to."""
    src = INDEX.read_text(encoding="utf-8")
    i = src.find("function retypeColumn(")
    assert i > 0
    body = src[i:src.index("\nfunction colTypeHe", i)]
    assert "קישור ללוח" in body, body
    assert "method:'POST'" not in body.replace(" ", ""), body
