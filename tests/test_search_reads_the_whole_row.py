"""חיפוש חופשי קורא את כל השורה — ועונה לפני שהוא נגמר, רק בזמן.

Three faults in one screen, reported together because on a large board they
look like one: "the search takes a long time to give a correct answer, it says
there are no matching records while it is still scanning, and it cannot find a
רשות by name".

**It could not find a רשות by name.** The free-text box read four things off a
row — the title, the description, the item's number and the people on it — and
nothing else. "רשות" is a COLUMN, and so is nearly everything a board is
actually arranged by, so none of them answered. Below the client threshold the
browser was no better; past it the server's answer is the whole of what the
screen shows, and there was nothing to fall back on.

**It said "no results" while still scanning.** Past the threshold the answer
takes a round trip. In that gap the only thing left to filter was the one page
of rows this browser happens to hold, which answers with nothing on a board of
fifteen thousand — so the board printed "אין תוצאות לסינון הנוכחי" over a
search that had not been run, and filled with rows seconds later. A question in
flight is not an answer of nothing.

**It took a long time.** Every row was asked for its assignees through a lazy
relationship, so one keystroke on a board of fifteen thousand items cost
fifteen thousand and eleven queries. The matching was never the expensive part;
the round trip per row was.

And the one that is easy to lose: the browser and the server must search the
SAME things. A board that crosses the threshold overnight must not start or
stop finding the same row.
"""
import json
import pathlib
import re
import subprocess
import sys

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import main as cityos_main  # noqa: E402
from models import Task, User  # noqa: E402

SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


@pytest.fixture
def counted():
    """Count SQL statements issued while the block runs."""
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


def _board(client, admin_id, name="לוח רשויות"):
    return client.post("/api/boards", json={"actor_id": admin_id, "name": name}).json()["id"]


def _cols(client, bid, admin_id, extra):
    """Add columns to the board and hand back the ids they were given."""
    cur = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cur + extra})
    assert r.status_code == 200, r.text
    got = r.json()["columns"]
    return [next(c["id"] for c in got if c.get("title") == x["title"]) for x in extra]


def _item(client, bid, admin_id, title, cells=None):
    tid = client.post("/api/tasks", json={"actor_id": admin_id, "board_id": bid,
                                          "title": title}).json()["id"]
    if cells:
        r = client.patch(f"/api/tasks/{tid}", json={"actor_id": admin_id, "custom_fields": cells})
        assert r.status_code == 200, r.text
    return tid


def _found(client, bid, uid, text):
    """The titles the free-text box answers with."""
    r = client.post(f"/api/boards/{bid}/items/query",
                    json={"user_id": uid, "q": text, "limit": 50})
    assert r.status_code == 200, r.text
    return [i.get("title") for i in r.json()["items"]]


# ── the board's own columns answer the search ─────────────────────────────
def test_an_item_is_found_by_the_authority_named_in_its_column(client, admin_id):
    """The whole of the report: typing a רשות's name finds the items whose
    רשות column holds it. It is a column, not a title, and a search box that
    reads only titles is a search box that cannot answer the question this
    board exists to answer."""
    bid = _board(client, admin_id)
    (auth,) = _cols(client, bid, admin_id, [{"type": "text", "title": "רשות"}])
    _item(client, bid, admin_id, "תיקון מדרכה", {auth: "עיריית חיפה"})
    _item(client, bid, admin_id, "גיזום עצים", {auth: "עיריית תל אביב"})
    assert _found(client, bid, admin_id, "חיפה") == ["תיקון מדרכה"]
    assert _found(client, bid, admin_id, "תל אביב") == ["גיזום עצים"]


def test_a_chosen_option_is_a_word_somebody_can_search_for(client, admin_id):
    """A multi-select holds a list and a status holds either the label or the
    option's stable id, depending on whether the grid, a form or the monday
    import wrote it. All three are the same value to the person looking at the
    board, so all three answer."""
    bid = _board(client, admin_id)
    drop, stat = _cols(client, bid, admin_id, [
        {"type": "dropdown", "title": "סוג", "options": ["תשתיות", "חינוך"]},
        {"type": "status", "title": "שלב",
         "options": [{"id": "o1", "label": "בבדיקה"}, {"id": "o2", "label": "אושר"}]}])
    _item(client, bid, admin_id, "א", {drop: ["תשתיות"], stat: "בבדיקה"})
    _item(client, bid, admin_id, "ב", {drop: ["חינוך"], stat: "o2"})
    assert _found(client, bid, admin_id, "תשתיות") == ["א"]
    assert _found(client, bid, admin_id, "בבדיקה") == ["א"]
    # written as the option's id by a form — the label is still what is typed
    assert _found(client, bid, admin_id, "אושר") == ["ב"]


def test_an_item_is_found_by_the_title_of_what_it_is_linked_to(client, admin_id):
    """A רשות is as often a connect column pointing at a board of them as it
    is a text cell. The browser has always searched connect cells off the
    titles in its link cache; past the threshold it holds no such thing, so
    the server resolves them — and the same search has to answer either side
    of the threshold."""
    auth_b = _board(client, admin_id, "רשויות")
    haifa = _item(client, auth_b, admin_id, "עיריית חיפה")
    tlv = _item(client, auth_b, admin_id, "עיריית תל אביב")
    work = _board(client, admin_id, "עבודות")
    (col,) = _cols(client, work, admin_id, [
        {"type": "connect", "title": "רשות",
         "connect": {"board_ids": [auth_b], "multiple": True}}])
    _item(client, work, admin_id, "תיקון מדרכה", {col: [haifa]})
    _item(client, work, admin_id, "גיזום עצים", {col: [tlv]})
    assert _found(client, work, admin_id, "חיפה") == ["תיקון מדרכה"]
    assert _found(client, work, admin_id, "עיריית") == ["תיקון מדרכה", "גיזום עצים"]


def test_a_search_still_finds_what_it_always_found(client, admin_id):
    """Reading more off a row must not stop it reading what it read before."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id, "גשר הירקון")
    client.patch(f"/api/tasks/{tid}", json={"actor_id": admin_id,
                                            "description": "בדיקת תמיכות"})
    assert _found(client, bid, admin_id, "ירקון") == ["גשר הירקון"]
    assert _found(client, bid, admin_id, "תמיכות") == ["גשר הירקון"]
    uid = client.get(f"/api/tasks/{tid}?user_id={admin_id}").json()["item_uid"]
    assert _found(client, bid, admin_id, str(uid)) == ["גשר הירקון"]


def test_a_tick_answers_to_a_word_and_only_to_the_whole_of_it(client, admin_id):
    """A checkbox has no content, so it answers to the word the board shows
    for a tick — and to the WHOLE of that word, which is the one place in this
    search that is not a substring match.

    The reason is specific rather than fastidious. Every other word in the
    haystack is something a person typed into one row, so over-matching it
    costs a few rows. "מסומן" is a word this system invents for every ticked
    row on the board, so matching it on "מס" — a prefix of מסמך, מספר, מסירה —
    would answer an ordinary search with half the board.
    """
    bid = _board(client, admin_id)
    (done,) = _cols(client, bid, admin_id, [{"type": "checkbox", "title": "בוצע"}])
    _item(client, bid, admin_id, "א", {done: True})
    _item(client, bid, admin_id, "ב", {done: False})
    assert _found(client, bid, admin_id, "מסומן") == ["א"]
    # the stored value is never the word
    assert _found(client, bid, admin_id, "true") == []
    # …and a prefix of it does not drag the ticked rows into an ordinary search
    assert _found(client, bid, admin_id, "מס") == []
    assert _found(client, bid, admin_id, "ומן") == []


# ── every column the board draws, without an exception list ──────────────
def test_every_kind_of_column_answers_the_search(client, admin_id, member_id):
    """The rule, stated as a matrix rather than as prose: a column the board
    DRAWS is a column the search box answers for.

    The first pass at this left four kinds out, and every one of them was a
    value sitting in plain sight on a row that typing it could not find — a
    people cell (it stores ids), a date (it stores ISO and shows dd/mm/yyyy),
    a tick, and a mirror. This test is the list, so the next column type
    added to the product has somewhere obvious to be added.
    """
    bid = _board(client, admin_id, "כל הסוגים")
    ids = _cols(client, bid, admin_id, [
        {"type": "text", "title": "הערה"},
        {"type": "long_text", "title": "תיאור"},
        {"type": "email", "title": "דואל"},
        {"type": "phone", "title": "טלפון"},
        {"type": "number", "title": "תקציב"},
        {"type": "rating", "title": "דירוג"},
        {"type": "status", "title": "שלב",
         "options": [{"id": "o1", "label": "אושר סופית"}]},
        {"type": "dropdown", "title": "סוג", "options": ["תשתיות חוץ"]},
        {"type": "date", "title": "יעד"},
        {"type": "timeline", "title": "טווח"},
        {"type": "files", "title": "קבצים"},
        {"type": "accounts", "title": "חשבון"},
    ])
    (txt, long, mail, tel, num, rate, stat, drop, day, span, files, acct) = ids
    # Somebody OTHER than the board's creator in the people cell, deliberately:
    # a board is born with starter items the creator is on, so searching the
    # creator's name would be answered by the built-in אחראים and prove
    # nothing about the people COLUMN.
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    with Session(cityos_main.engine) as db:
        theirname = db.query(User).filter(User.id == member_id).first().name
    (ppl,) = _cols(client, bid, admin_id, [{"type": "people", "title": "מטפל"}])
    _item(client, bid, admin_id, "פריט בדיקה", {
        txt: "מגדל המים", long: "תיאור ארוך על שיקום",
        mail: "ronit@hadera.gov.il", tel: "050-1234567",
        num: 4821, rate: 5,
        # written as the option's stable id, which is what a form and the
        # monday import store — the label is still the word somebody types
        stat: "o1", drop: ["תשתיות חוץ"],
        day: "2026-11-04", span: {"from": "2026-11-04", "to": "2026-12-01"},
        files: [{"name": "נספח תכנון.pdf", "url": "/u/x.pdf"}],
        acct: "חברת מקורות", ppl: [member_id]})

    for what, q in [
            ("text", "מגדל המים"), ("long_text", "שיקום"),
            ("email", "ronit@hadera"), ("phone", "1234567"),
            ("number", "4821"), ("rating", "5"),
            ("status, by its label", "אושר סופית"),
            ("dropdown", "תשתיות חוץ"),
            # a date STORES 2026-11-04 and the board SHOWS 04/11/2026. Both
            # answer: the first is what somebody pastes out of another
            # system, the second is what they read off the screen and retype.
            ("date as shown", "04/11/2026"), ("date as stored", "2026-11-04"),
            ("timeline, its far end as shown", "01/12/2026"),
            ("files, by name", "נספח תכנון"), ("accounts", "חברת מקורות"),
            # a people cell stores ids. Nobody searches "7".
            ("people, by name", theirname)]:
        # Membership, not the whole answer: a board is born with starter
        # items carrying ids of their own, so a one-character probe like the
        # rating's "5" is legitimately answered by more than this row. What
        # this test is for is that the row IS among them for every type.
        assert "פריט בדיקה" in _found(client, bid, admin_id, q), what
    # …and the search still says no when the board holds no such thing
    assert _found(client, bid, admin_id, "זזזזזז") == []


def test_a_people_cell_is_its_names_and_never_its_ids(client, admin_id, member_id):
    """Replaced rather than added to: an id left in the haystack is a row
    that answers a search for a digit."""
    bid = _board(client, admin_id, "לוח אנשים")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    (ppl,) = _cols(client, bid, admin_id, [{"type": "people", "title": "מטפל"}])
    _item(client, bid, admin_id, "שורה", {ppl: [member_id]})
    with Session(cityos_main.engine) as db:
        theirname = db.query(User).filter(User.id == member_id).first().name
    assert _found(client, bid, admin_id, theirname) == ["שורה"]
    # …and the id itself is not in the haystack at all. Asserted on the cell
    # reader rather than through a search, because a user id is a small
    # number and every board has rows whose מזהה פריט happens to contain it —
    # a confound, not a second route in.
    sub, whole = cityos_main._searchable_words(
        "people", [member_id], {member_id: theirname})
    assert sub == [theirname] and whole == [], (sub, whole)
    assert str(member_id) not in sub


def test_the_automatic_columns_answer_too(client, admin_id):
    """מועד יצירה and יוצר הרשומה keep nothing in custom_fields — they are
    read off the item — so they reached the haystack through none of the
    paths above and had to be fetched the way the filter engine gets them."""
    bid = _board(client, admin_id, "לוח אוטומטי")
    _cols(client, bid, admin_id, [{"type": "created_by", "title": "יוצר"},
                                  {"type": "created_at", "title": "נוצר"}])
    _item(client, bid, admin_id, "שורה")
    with Session(cityos_main.engine) as db:
        myname = db.query(User).filter(User.id == admin_id).first().name
        made = db.query(Task).filter(Task.title == "שורה").order_by(
            Task.id.desc()).first().created_at
    # Membership rather than the whole answer: a board is born with starter
    # items and this creator made those too, so they answer the same search —
    # which is the column working, not a stray match.
    assert "שורה" in _found(client, bid, admin_id, myname)
    assert "שורה" in _found(client, bid, admin_id, made.strftime("%d/%m/%Y"))


def test_a_mirror_column_answers_and_does_not_cost_a_query_a_row(
        client, admin_id, counted):
    """A mirror is a field of a LINKED item, so the obvious way to read one is
    a query per row per column — 750ms and five thousand queries on a board of
    five thousand, which is why it was left out of the search at first.

    That was a fact about the naive path and not about the column. Warming the
    links once first brings the same work to 98ms and eighteen queries, so the
    column is in the search like any other and the cost does not grow with the
    board.
    """
    far = _board(client, admin_id, "רשויות למראה")
    haifa = _item(client, far, admin_id, "עיריית חיפה")
    work = _board(client, admin_id, "עבודות למראה")
    (link,) = _cols(client, work, admin_id, [
        {"type": "connect", "title": "רשות",
         "connect": {"board_ids": [far], "multiple": True}}])
    (_mir,) = _cols(client, work, admin_id, [
        {"type": "mirror", "title": "שם הרשות",
         "mirror_of": {"connect": link, "field": "title"}}])
    for i in range(40):
        _item(client, work, admin_id, f"עבודה {i:02d}", {link: [haifa]})
    counted.n = 0
    assert len(_found(client, work, admin_id, "חיפה")) == 40
    assert counted.n < 40, f"{counted.n} queries for 40 rows — it is per row again"


def test_a_formula_is_the_one_column_neither_side_can_answer_for(client, admin_id):
    """Said out loud rather than left to be discovered. A formula is computed
    and never stored, and the engine that computes it lives in the browser —
    so searching it there and not here would mean a board that found a row
    until it grew past the client threshold and then stopped finding it."""
    bid = _board(client, admin_id, "לוח נוסחה")
    _cols(client, bid, admin_id, [{"type": "formula", "title": "סהכ",
                                   "formula": "1+1"}])
    tid = _item(client, bid, admin_id, "שורה")
    stored = client.get(f"/api/tasks/{tid}?user_id={admin_id}").json()
    assert not (stored.get("custom_fields") or {}).get("סהכ"), \
        "a formula started being stored — it can be searched now, so search it"


# ── and only the columns this reader may see ──────────────────────────────
def test_a_column_somebody_may_not_see_does_not_narrow_the_board_for_them(
        client, admin_id, guinea_id):
    """A hidden column answering a search would be answering a question about
    hidden data with a row set, and a row set is an answer: type names until
    the board narrows and you have read the column."""
    bid = _board(client, admin_id)
    (secret,) = _cols(client, bid, admin_id, [{"type": "text", "title": "סודי"}])
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    _item(client, bid, admin_id, "שורה", {secret: "מוכתר"})
    assert _found(client, bid, admin_id, "מוכתר") == ["שורה"]
    client.post(f"/api/boards/{bid}/columns/{secret}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"})
    assert _found(client, bid, guinea_id, "מוכתר") == []
    assert _found(client, bid, admin_id, "מוכתר") == ["שורה"], "the admin is unaffected"


def test_nor_does_a_connect_column_they_may_not_see(client, admin_id, guinea_id):
    """The same rule, through the other door. A connect cell narrows the board
    by the TITLE of something on another board, which is no less a disclosure
    for being one hop away."""
    auth_b = _board(client, admin_id, "רשויות חסויות")
    haifa = _item(client, auth_b, admin_id, "עיריית חיפה")
    work = _board(client, admin_id, "עבודות חסויות")
    (col,) = _cols(client, work, admin_id, [
        {"type": "connect", "title": "רשות",
         "connect": {"board_ids": [auth_b], "multiple": True}}])
    _item(client, work, admin_id, "תיקון מדרכה", {col: [haifa]})
    client.post(f"/api/boards/{work}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert _found(client, work, guinea_id, "חיפה") == [], \
        "a reader with no access to the other board read a title off it"
    client.post(f"/api/boards/{auth_b}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
    assert _found(client, work, guinea_id, "חיפה") == ["תיקון מדרכה"], \
        "…and one who may see it is told nothing"
    client.post(f"/api/boards/{work}/columns/{col}/permissions",
                json={"actor_id": admin_id, "user_id": guinea_id, "perm": "none"})
    assert _found(client, work, guinea_id, "חיפה") == [], \
        "the column itself was hidden from them and still answered"


# ── the cost of asking ────────────────────────────────────────────────────
def test_the_search_does_not_ask_the_database_once_per_row(client, admin_id, counted):
    """The people on a row arrive WITH the rows. They used to be loaded one
    lazy relationship at a time — the toolbar's people filter reads them and
    so does the shape the condition tree matches against — so a board of
    fifteen thousand items cost fifteen thousand queries for one keystroke.

    Pinned as a ceiling rather than an exact number: what matters is that it
    does not grow with the board.
    """
    bid = _board(client, admin_id)
    for i in range(60):
        client.post("/api/tasks", json={"actor_id": admin_id, "board_id": bid,
                                        "title": f"פריט {i:03d}"})
    counted.n = 0
    _found(client, bid, admin_id, "פריט 042")
    assert counted.n < 40, f"{counted.n} queries for a 60-row board — it is per row again"


# ── the browser searches the same things ──────────────────────────────────
def test_the_browser_reads_the_boards_columns_too():
    i = SRC.index("function searchWordsOf(t)")
    body = SRC[i:SRC.index("\n}", i)]
    assert "customColumns()" in body and "cellSearchWords(c,cf[c.id],out,exact)" in body
    assert "t.title" in body and "t.description" in body
    i = SRC.index("function applyFilters(tasks){")
    body = SRC[i:SRC.index("\n}", i)]
    assert "searchRow(t,q)" in body, "the local engine still reads only the title"
    assert "linkNamesOf(t)" in body


def test_the_two_sides_leave_out_the_same_two_columns():
    """A board that crosses the client threshold overnight must not start or
    stop finding the same row, so what is skipped is the same on both sides —
    and it is exactly two things, for two different reasons.

    CONNECT is not skipped so much as answered elsewhere: its cell holds ids,
    and its words are the titles at the other end.

    FORMULA is the one column neither side can answer for. It is computed and
    never stored, and the engine that computes it lives in the browser — so
    searching it there and not on the server would mean a board that found a
    row until it grew past the threshold and then stopped.
    """
    i = SRC.index("function searchWordsOf(t)")
    js = SRC[i:SRC.index("\n}", i)]
    assert "c.type==='connect'||c.type==='formula'" in js, js
    assert "mirror" not in js, "the browser skips a mirror the server now reads"
    py = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    i = py.index("what the free-text box actually searches")
    win = py[i:i + 3000]
    assert 'ctype in ("connect", "formula")' in win, win[:400]
    assert "_col_perm(c, user_id, my_role)" in py, "a hidden column answers the search"


def test_the_browser_and_the_server_agree_on_the_word_for_a_tick():
    py = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'TICK_WORD = "מסומן"' in py
    assert "const TICK_WORD='מסומן'" in SRC
    # …and the browser matches it whole, like the server does
    i = SRC.index("function searchRow(t,q)")
    body = SRC[i:SRC.index("\n}", i)]
    assert ".includes(q)" in body and "===q" in body, body


# ── a question in flight is not an answer ─────────────────────────────────
def test_a_search_still_running_does_not_report_an_empty_board():
    i = SRC.index("function searchPending()")
    body = SRC[i:SRC.index("\n}", i)]
    assert "Paged.pending" in body and "filterMode()==='server'" in body
    i = SRC.index("function cutMatchesNothing()")
    body = SRC[i:SRC.index("\n}", i)]
    assert "searchPending()" in body
    assert "Paged.matched===0" in body, "it read the board's row count, not the cut's"
    i = SRC.index("function vTable(el){")
    body = SRC[i:SRC.index("\n  /* Only the first group", i)]
    assert "searchPending()" in body and "searchingHTML()" in body
    assert "pending?searchingHTML():noMatchHTML()" in body


def test_the_debounce_marks_the_question_asked_before_it_goes_out():
    """The quarter second between the keystroke and the request is where the
    bug lived: no answer yet AND no request yet."""
    i = SRC.index("function refreshToolbar()")
    body = SRC[i:SRC.index("\n}", i)]
    assert "Paged.pending=true" in body
    assert body.index("Paged.pending=true") < body.index("_pagedTimer=setTimeout")


def test_a_new_search_is_never_dropped_for_one_already_in_flight():
    """Typing on while a three-second request runs used to ask nothing at all,
    and the answer that finally painted the board was the previous query's."""
    i = SRC.index("const Paged = {")
    body = SRC[i:SRC.index("\n};", i)]
    assert "if(this.loading && !fresh) return;" in body
    assert "mine!==this.seq" in body, "the older answer must still be thrown away"


# ── and the two sides really do agree, cell by cell ──────────────────────
# Every test above this line checks one side. This one runs BOTH over the
# same cells and compares the words they produce, because "the browser and
# the server search the same things" is the rule that is easiest to state and
# hardest to keep: they are two implementations in two languages, edited
# months apart, and the failure is silent — a board that finds a row until it
# grows past the client threshold, and then does not.
#
# Compared as sets: the haystack is searched with "is the query inside any of
# these", so the order the words come out in is not part of the answer.
_AGREE_CASES = [
    ({"type": "text", "id": "c"}, "מגדל המים"),
    ({"type": "number", "id": "c"}, 4821),
    ({"type": "dropdown", "id": "c"}, ["תשתיות חוץ"]),
    ({"type": "status", "id": "c",
      "options": [{"id": "o1", "label": "אושר סופית"}]}, "o1"),
    ({"type": "status", "id": "c",
      "options": [{"id": "o1", "label": "אושר סופית"}]}, "אושר סופית"),
    ({"type": "date", "id": "c"}, "2026-11-04"),
    ({"type": "timeline", "id": "c"}, {"from": "2026-11-04", "to": "2026-12-01"}),
    ({"type": "checkbox", "id": "c"}, True),
    ({"type": "checkbox", "id": "c"}, False),
    ({"type": "people", "id": "c"}, [7]),
    ({"type": "files", "id": "c"}, [{"name": "נספח.pdf", "url": "/u/x"}]),
    ({"type": "created_at", "id": "c"}, "2026-11-04T10:23:45"),
    ({"type": "created_by", "id": "c"}, [7]),
]


def _grab(name):
    """One function out of index.html, by balanced braces — the same trick the
    .mjs harnesses use."""
    i = re.search(r"^function %s\(" % name, SRC, re.M).start()
    j, d = SRC.index("{", i), 0
    for k in range(j, len(SRC)):
        if SRC[k] == "{":
            d += 1
        elif SRC[k] == "}":
            d -= 1
            if not d:
                return SRC[i:k + 1]
    raise AssertionError("unbalanced: " + name)


def test_the_browser_and_the_server_read_a_cell_the_same_way(tmp_path):
    js = tmp_path / "cells.mjs"
    js.write_text(
        "const st={users:[{id:7,name:'רות לוי'}]};\n"
        + re.search(r"^const TICK_WORD=.*$", SRC, re.M).group(0) + "\n"
        + _grab("cellWords") + "\n" + _grab("fdatePlain") + "\n"
        + _grab("cellSearchWords") + "\n"
        + "const CASES=" + json.dumps(_AGREE_CASES, ensure_ascii=False) + ";\n"
        "console.log(JSON.stringify(CASES.map(([c,v])=>{"
        "const o=[],e=[];cellSearchWords(c,v,o,e);return [o,e];})));\n",
        encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    theirs = json.loads(r.stdout)

    bad = []
    for (col, v), js_out in zip(_AGREE_CASES, theirs):
        vocab = ({str(o["id"]): o["label"] for o in col.get("options") or []}
                 if col["type"] == "status" else None)
        sub, whole = cityos_main._searchable_words(col["type"], v, {7: "רות לוי"}, vocab)
        if (set(sub), set(whole)) != (set(js_out[0]), set(js_out[1])):
            bad.append(f"{col['type']} {v!r}: server={[sub, whole]} browser={js_out}")
    assert not bad, "\n".join(bad)
