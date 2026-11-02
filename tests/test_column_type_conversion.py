"""שינוי סוג עמודה — והערכים שכבר בה עוברים איתה.

A board admin could always retype a column: PATCH /api/boards/{id} takes a
full replacement of the column definitions, so naming a text column
"dropdown" in that payload retypes it. What it could never do is the half
that matters. That branch replaces DEFINITIONS and never touches a cell, and
every type stores its value in its own shape — a dropdown cell is a LIST of
strings, a status cell is a {label,color} snapshot, a timeline is a pair of
dates. So a column retyped that way came back holding values the new type
cannot read, and the board drew the whole column empty. Nothing in the
browser offered it either, which is the only reason nobody had done it to a
real board.

Both halves move together now, through one rule that is the same for every
pair of types:

    the cell is read into the WORDS it says, and those words are written
    back in the shape the new type holds. Where the new type cannot read a
    word the cell is emptied — and how many cells that will be is counted
    and shown before anything is written.

One rule rather than a matrix of a hundred and thirty-two conversions, and
it is the rule a person already has in their head: a column says something,
and the question is whether the new type can still say it.

What is pinned here:

  · the round trip for each type — the words come out and go back in
  · a cell the target cannot read is EMPTIED, not left holding the old
    shape, which would draw blank and behave as if it still had a value
  · items in the recycle bin are converted too. A cell left in the old shape
    is a wrong cell the day somebody restores the item, and a restore is the
    worst possible place to discover it
  · a status or dropdown source keeps the order and the whole vocabulary its
    admin wrote, options nobody has picked included
  · only a board admin, only on a column that holds a value of its own, and
    never past the cap the target type can show
  · a form that asks about the column has to be agreed to out loud, the same
    409 bargain the board PATCH strikes
  · the board's log says the type changed, in the board's own language, and
    does not say the column was deleted
"""
import pathlib
import shutil
import subprocess

import pytest

import main as cityos_main

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def _board(client, admin_id, name="לוח המרה"):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _col(client, admin_id, bid, **col):
    """Add one custom column and return its definition."""
    r = client.patch(f"/api/boards/{bid}",
                     json={"user_id": admin_id, "columns": [col]})
    assert r.status_code == 200, r.text
    return r.json()["columns"][0]


def _item(client, admin_id, bid, title, cid=None, val=None):
    tid = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                          "user_id": admin_id}).json()["id"]
    if cid is not None:
        r = client.patch(f"/api/tasks/{tid}",
                         json={"user_id": admin_id, "custom_fields": {cid: val}})
        assert r.status_code == 200, r.text
    return tid


def _cells(client, admin_id, bid, cid, titles):
    """{title: cell} for the items this test made — a new board arrives with
    three seeded demo items, and they are not what any of this is about."""
    d = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    return {t["title"]: (t.get("custom_fields") or {}).get(cid)
            for t in d["tasks"] if t["title"] in titles}


def _coldef(client, admin_id, bid, cid):
    d = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    return next(c for c in d["columns"] if c["id"] == cid)


def _plan(client, admin_id, bid, cid, to):
    return client.get(f"/api/boards/{bid}/columns/{cid}/retype"
                      f"?to={to}&user_id={admin_id}")


def _do(client, admin_id, bid, cid, to, **extra):
    return client.post(f"/api/boards/{bid}/columns/{cid}/retype",
                       json={"user_id": admin_id, "to": to, **extra})


# ── the rule, once per shape ────────────────────────────────────────────────

def test_text_becomes_a_list_of_its_own_values(client, admin_id):
    """The case this was asked for: the column already holds the list,
    somebody typed it out by hand, and the declaration is what is missing."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    for t, v in [("א", "תשתיות"), ("ב", "חינוך"), ("ג", "תשתיות"), ("ד", "")]:
        _item(client, admin_id, bid, t, cid, v)

    p = _plan(client, admin_id, bid, cid, "dropdown")
    assert p.status_code == 200, p.text
    p = p.json()
    # sorted — a text column has no order of its own to preserve — and counted,
    # so the dialog can say how much of the board this touches
    assert [(o["value"], o["count"]) for o in p["options"]] == \
        [("חינוך", 1), ("תשתיות", 2)]
    assert (p["filled"], p["keep"], p["lose"]) == (3, 3, 0)
    assert p["from"] == "text" and p["to"] == "dropdown"

    r = _do(client, admin_id, bid, cid, "dropdown")
    assert r.status_code == 200, r.text
    col = _coldef(client, admin_id, bid, cid)
    assert col["type"] == "dropdown" and col["options"] == ["חינוך", "תשתיות"]
    assert _cells(client, admin_id, bid, cid, "אבגד") == {
        "א": ["תשתיות"], "ב": ["חינוך"], "ג": ["תשתיות"], "ד": None}


def test_text_becomes_a_status_with_a_vocabulary_and_colours(client, admin_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="שלב")["id"]
    _item(client, admin_id, bid, "א", cid, "בביצוע")
    _item(client, admin_id, bid, "ב", cid, "הסתיים")

    assert _do(client, admin_id, bid, cid, "status").status_code == 200
    col = _coldef(client, admin_id, bid, cid)
    assert col["type"] == "status"
    assert [o["label"] for o in col["options"]] == ["בביצוע", "הסתיים"]
    # every option gets an id and a colour — a status cell points at the
    # option, which is what makes renaming it later carry the cells with it
    assert all(o["id"] and o["color"].startswith("#") for o in col["options"])
    cells = _cells(client, admin_id, bid, cid, "אב")
    assert cells["א"]["label"] == "בביצוע"
    assert cells["א"]["id"] == next(o["id"] for o in col["options"]
                                    if o["label"] == "בביצוע")


def test_a_status_keeps_the_vocabulary_its_admin_wrote(client, admin_id):
    """A status column already HAS a list, in an order somebody chose.
    Sorting it would scramble that, and dropping the options nobody has
    picked yet would quietly delete the admin's work."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="status", title="שלב",
               options=[{"label": "תכנון", "color": "#0073ea"},
                        {"label": "ביצוע", "color": "#00c875"},
                        {"label": "אחזקה", "color": "#fdab3d"}])["id"]
    pick = {o["label"]: o for o in _coldef(client, admin_id, bid, cid)["options"]}
    _item(client, admin_id, bid, "א", cid, pick["ביצוע"])
    _item(client, admin_id, bid, "ב", cid, pick["תכנון"])

    p = _plan(client, admin_id, bid, cid, "dropdown").json()
    # the declared order, not alphabetical — and אחזקה survives at nought uses
    assert [(o["value"], o["count"]) for o in p["options"]] == \
        [("תכנון", 1), ("ביצוע", 1), ("אחזקה", 0)]
    assert _do(client, admin_id, bid, cid, "dropdown").status_code == 200
    assert _coldef(client, admin_id, bid, cid)["options"] == \
        ["תכנון", "ביצוע", "אחזקה"]
    assert _cells(client, admin_id, bid, cid, "אב") == {"א": ["ביצוע"], "ב": ["תכנון"]}


def test_a_number_reads_like_the_figure_did(client, admin_id):
    """3 and not 3.0 — a value somebody has to recognise twice is a value
    that did not survive the conversion."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="number", title="אזור")["id"]
    _item(client, admin_id, bid, "א", cid, 3)
    _item(client, admin_id, bid, "ב", cid, 12.5)
    assert _do(client, admin_id, bid, cid, "text").status_code == 200
    assert _cells(client, admin_id, bid, cid, "אב") == {"א": "3", "ב": "12.5"}


def test_text_that_is_not_a_number_empties_the_cell(client, admin_id):
    """And the dialog said so first — that count is the whole of what there
    is to agree to."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="כמות")["id"]
    _item(client, admin_id, bid, "מספר", cid, "42")
    _item(client, admin_id, bid, "מילה", cid, "הרבה")

    p = _plan(client, admin_id, bid, cid, "number").json()
    assert (p["filled"], p["keep"], p["lose"]) == (2, 1, 1)
    # the losses are shown first: they are the part somebody has to read
    assert p["samples"][0] == {"before": "הרבה", "after": None}

    assert _do(client, admin_id, bid, cid, "number").status_code == 200
    # emptied, not left holding the old shape — a cell that still said "הרבה"
    # would draw blank and behave as though it had a value
    assert _cells(client, admin_id, bid, cid, ["מספר", "מילה"]) == {
        "מספר": 42, "מילה": None}


def test_a_rating_only_takes_what_five_stars_can_show(client, admin_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="number", title="ציון")["id"]
    _item(client, admin_id, bid, "טוב", cid, 4)
    _item(client, admin_id, bid, "גבוה", cid, 9)
    assert _do(client, admin_id, bid, cid, "rating").status_code == 200
    assert _cells(client, admin_id, bid, cid, ["טוב", "גבוה"]) == {
        "טוב": 4, "גבוה": None}


def test_only_something_that_is_an_address_becomes_one(client, admin_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="קשר")["id"]
    _item(client, admin_id, bid, "יש", cid, "dana@mashcal.co.il")
    _item(client, admin_id, bid, "אין", cid, "דנה")
    assert _do(client, admin_id, bid, cid, "email").status_code == 200
    assert _cells(client, admin_id, bid, cid, ["יש", "אין"]) == {
        "יש": "dana@mashcal.co.il", "אין": None}


def test_a_date_becomes_a_timeline_and_back(client, admin_id):
    """A timeline says two words, a start and an end, so it survives the
    round trip through a list instead of collapsing to one date."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="date", title="יעד")["id"]
    _item(client, admin_id, bid, "א", cid, "2026-03-01")
    assert _do(client, admin_id, bid, cid, "timeline").status_code == 200
    assert _cells(client, admin_id, bid, cid, "א") == {
        "א": {"from": "2026-03-01", "to": "2026-03-01"}}

    r = _do(client, admin_id, bid, cid, "dropdown")
    assert r.status_code == 200, r.text
    assert _coldef(client, admin_id, bid, cid)["options"] == ["2026-03-01"]


def test_a_typed_date_is_read_the_way_people_write_it(client, admin_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="מתי")["id"]
    _item(client, admin_id, bid, "נקודות", cid, "01.03.2026")
    _item(client, admin_id, bid, "לוכסן", cid, "1/3/2026")
    _item(client, admin_id, bid, "לא", cid, "בקרוב")
    assert _do(client, admin_id, bid, cid, "date").status_code == 200
    assert _cells(client, admin_id, bid, cid, ["נקודות", "לוכסן", "לא"]) == {
        "נקודות": "2026-03-01", "לוכסן": "2026-03-01", "לא": None}


def test_a_checkbox_is_ticked_only_by_a_word_that_means_yes(client, admin_id):
    """There is no third state to put a value nobody can read into: a box is
    either ticked or it is not."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="הושלם")["id"]
    _item(client, admin_id, bid, "כן", cid, "כן")
    _item(client, admin_id, bid, "לא", cid, "לא")
    assert _do(client, admin_id, bid, cid, "checkbox").status_code == 200
    assert _cells(client, admin_id, bid, cid, ["כן", "לא"]) == {
        "כן": True, "לא": None}
    # and back out again, as the word it says
    assert _do(client, admin_id, bid, cid, "text").status_code == 200
    assert _cells(client, admin_id, bid, cid, ["כן", "לא"]) == {
        "כן": "כן", "לא": None}


def test_a_name_becomes_a_person_only_if_the_board_has_them(client, admin_id,
                                                            member_id):
    """The same gate every other door uses — a conversion cannot invent a
    board member, and will not name somebody who was never invited."""
    bid = _board(client, admin_id)
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    who = client.get(f"/api/boards/{bid}/members?user_id={admin_id}").json()
    name = next(m["name"] for m in who["members"] if m["user_id"] == member_id)

    cid = _col(client, admin_id, bid, type="text", title="בודק")["id"]
    _item(client, admin_id, bid, "חבר", cid, name)
    _item(client, admin_id, bid, "זר", cid, "מישהו אחר לגמרי")
    assert _do(client, admin_id, bid, cid, "people").status_code == 200
    assert _cells(client, admin_id, bid, cid, ["חבר", "זר"]) == {
        "חבר": [member_id], "זר": None}


def test_a_cell_in_the_recycle_bin_is_converted_too(client, admin_id):
    """Otherwise the restore is where the old shape surfaces, weeks later and
    as a cell that silently reads empty."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    _item(client, admin_id, bid, "חי", cid, "תברואה")
    binned = _item(client, admin_id, bid, "בסל", cid, "רווחה")
    assert client.delete(f"/api/tasks/{binned}?user_id={admin_id}").status_code == 200

    # a binned item's value still counts towards the vocabulary: it is a value
    # the column holds, and the item can come back
    p = _plan(client, admin_id, bid, cid, "dropdown").json()
    assert [o["value"] for o in p["options"]] == ["רווחה", "תברואה"]

    assert _do(client, admin_id, bid, cid, "dropdown").status_code == 200
    assert client.post(f"/api/tasks/{binned}/restore",
                       json={"user_id": admin_id}).status_code == 200
    assert _cells(client, admin_id, bid, cid, ("חי", "בסל")) == {
        "חי": ["תברואה"], "בסל": ["רווחה"]}


def test_an_empty_column_converts_to_an_empty_list(client, admin_id):
    """Not refused: declaring the column a list before anybody fills it in is
    a reasonable thing to want, and the options can be added by hand."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    _item(client, admin_id, bid, "א")
    r = _do(client, admin_id, bid, cid, "dropdown")
    assert r.status_code == 200, r.text
    assert r.json()["options"] == []
    assert _coldef(client, admin_id, bid, cid)["type"] == "dropdown"


def test_every_pair_of_types_is_allowed_and_leaves_a_readable_column(
        client, admin_id):
    """The matrix, walked. Not an assertion about any one conversion — those
    are above — but that none of the hundred and thirty-two 500s, and that
    the column is left as the type that was asked for."""
    bid = _board(client, admin_id, "מטריצה")
    kinds = sorted(cityos_main.COLUMN_RETYPE_TYPES)
    seeds = {"text": "4", "long_text": "4", "email": "a@b.co", "phone": "0501234567",
             "number": 4, "rating": 4, "dropdown": ["4"], "date": "2026-03-01",
             "timeline": {"from": "2026-03-01", "to": "2026-03-02"},
             "checkbox": True, "people": [admin_id]}
    for start in kinds:
        col = {"type": start, "title": f"עמודת {start}"}
        if start == "status":
            col["options"] = [{"label": "4", "color": "#0073ea"}]
        cid = _col(client, admin_id, bid, **col)["id"]
        val = seeds.get(start)
        if start == "status":
            val = _coldef(client, admin_id, bid, cid)["options"][0]
        _item(client, admin_id, bid, f"פריט {start}", cid, val)
        # one column walked through every other type in turn, so each outer
        # pass covers eleven conversions and the twelve passes cover the lot
        cur = start
        for to in kinds:
            if to == cur:
                assert _do(client, admin_id, bid, cid, to).status_code == 400
                continue
            p = _plan(client, admin_id, bid, cid, to)
            assert p.status_code == 200, (cur, to, p.text)
            r = _do(client, admin_id, bid, cid, to)
            assert r.status_code == 200, (cur, to, r.text)
            assert _coldef(client, admin_id, bid, cid)["type"] == to
            # and the board still renders — a cell left in an unreadable shape
            # is what this whole endpoint exists to prevent
            assert client.get(f"/api/boards/{bid}?user_id={admin_id}"
                              ).status_code == 200, (cur, to)
            cur = to


# ── what it refuses ─────────────────────────────────────────────────────────

def test_only_a_board_admin_may_change_a_type(client, admin_id, member_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    assert client.get(f"/api/boards/{bid}/columns/{cid}/retype"
                      f"?to=dropdown&user_id={member_id}").status_code == 403
    assert _do(client, member_id, bid, cid, "dropdown").status_code == 403
    assert _coldef(client, admin_id, bid, cid)["type"] == "text"


def test_a_column_that_holds_nothing_of_its_own_is_refused(client, admin_id):
    """A formula and a mirror compute from elsewhere; created_at, created_by
    and מזהה פריט are issued by the system; connect is a relationship and
    files point at uploads a filename cannot stand in for."""
    bid = _board(client, admin_id)
    for t in ("created_at", "created_by", "item_id", "files"):
        cid = _col(client, admin_id, bid, type=t, title=t)["id"]
        assert _do(client, admin_id, bid, cid, "text").status_code == 400, t
        assert client.get(f"/api/boards/{bid}/columns/{cid}/retype"
                          f"?to=text&user_id={admin_id}").status_code == 400, t


def test_the_target_has_to_be_a_type_a_value_can_be_built_for(client, admin_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    for to in ("files", "connect", "formula", "mirror", "item_id", "", "nonsense"):
        assert _do(client, admin_id, bid, cid, to).status_code == 400, to
    assert _coldef(client, admin_id, bid, cid)["type"] == "text"


def test_converting_a_column_to_what_it_already_is_is_refused(client, admin_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="dropdown", title="תחום",
               options=["א", "ב"])["id"]
    assert _do(client, admin_id, bid, cid, "dropdown").status_code == 400
    assert _coldef(client, admin_id, bid, cid)["options"] == ["א", "ב"]


def test_a_missing_board_or_column_is_404(client, admin_id):
    bid = _board(client, admin_id)
    assert _do(client, admin_id, bid, "col_nope", "text").status_code == 404
    assert _do(client, admin_id, 99999999, "col_x", "text").status_code == 404


def test_a_missing_body_is_422_not_500(client, admin_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    assert client.post(f"/api/boards/{bid}/columns/{cid}/retype"
                       f"?user_id={admin_id}").status_code == 422


def test_too_many_values_for_the_target_to_show_is_refused(client, admin_id):
    """A list nobody can scroll is not a list, and keeping the first N would
    empty the cells of everybody below the cut. A status column's ceiling is
    its own, and lower."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="חופשי")["id"]
    n = cityos_main.STATUS_COL_MAX + 1
    for i in range(n):
        _item(client, admin_id, bid, f"פריט {i}", cid, f"ערך {i}")

    p = _plan(client, admin_id, bid, cid, "status").json()
    assert p["too_many"] is True and p["max"] == cityos_main.STATUS_COL_MAX
    r = _do(client, admin_id, bid, cid, "status")
    assert r.status_code == 400 and str(n) in r.json()["detail"], r.text

    # the same values are still a perfectly good dropdown — the cap belongs
    # to the target, not to the column
    assert _plan(client, admin_id, bid, cid, "dropdown").json()["too_many"] is False
    assert _do(client, admin_id, bid, cid, "dropdown").status_code == 200
    assert _coldef(client, admin_id, bid, cid)["type"] == "dropdown"


# ── the promises a retype owes ──────────────────────────────────────────────

def test_a_form_asking_about_the_column_has_to_be_agreed_to(client, admin_id):
    """The same bargain the board PATCH strikes, in the same 409 shape — the
    browser has one handler for both."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    _item(client, admin_id, bid, "א", cid, "תשתיות")
    me = {"X-CityOS-User": str(admin_id)}
    fid = client.post(f"/api/boards/{bid}/forms", json={}, headers=me).json()["id"]
    assert client.post(f"/api/forms/{fid}/components",
                       json={"kind": "question", "field_key": cid, "label": "תחום"},
                       headers=me).status_code == 200
    assert client.patch(f"/api/forms/{fid}", json={"status": "PUBLISHED"},
                        headers=me).status_code == 200

    r = _do(client, admin_id, bid, cid, "dropdown")
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert [c["col_id"] for c in d["columns"]] == [cid]
    assert d["columns"][0]["new_type"] == "dropdown"
    assert d["columns"][0]["removed"] is False and d["columns"][0]["forms"]
    # refused means refused: nothing was written
    assert _coldef(client, admin_id, bid, cid)["type"] == "text"

    ok = _do(client, admin_id, bid, cid, "dropdown", confirm_columns=[cid])
    assert ok.status_code == 200, ok.text
    assert _coldef(client, admin_id, bid, cid)["type"] == "dropdown"


def test_the_board_log_says_the_type_changed_in_the_boards_own_language(
        client, admin_id):
    """A line reading "עמודה נמחקה" about a column still on the board is the
    one kind of log entry nobody can check — and "הסוג שונה לdropdown" is a
    line written for whoever wrote the code."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    _item(client, admin_id, bid, "א", cid, "תשתיות")
    assert _do(client, admin_id, bid, cid, "dropdown").status_code == 200

    rows = client.get(f"/api/boards/{bid}/activity?user_id={admin_id}")
    assert rows.status_code == 200, rows.text
    hit = [r for r in rows.json()["activity"]
           if r["field"] == "column" and r["action"] == "update"]
    assert len(hit) == 1, rows.json()["activity"]
    assert hit[0]["old"] == "תחום"
    assert "רשימה נפתחת" in hit[0]["new"], hit[0]["new"]
    # a board row opens nothing and can never be undone
    assert hit[0]["task_id"] is None and hit[0]["can_undo"] is False


def test_the_log_counts_the_cells_that_were_emptied(client, admin_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="כמות")["id"]
    _item(client, admin_id, bid, "מילה", cid, "הרבה")
    assert _do(client, admin_id, bid, cid, "number").status_code == 200
    rows = client.get(f"/api/boards/{bid}/activity?user_id={admin_id}").json()
    line = next(r for r in rows["activity"]
                if r["field"] == "column" and r["action"] == "update")
    assert "1 תאים התרוקנו" in line["new"], line["new"]


# ── the browser's half ──────────────────────────────────────────────────────

def test_the_two_lists_of_convertible_types_agree():
    """The menu decides whether to OFFER the entry and which types to show;
    the server decides whether to allow it. A type in one and not the other
    is either a menu item that always fails, or a conversion nobody can
    reach."""
    src = INDEX.read_text(encoding="utf-8")
    i = src.index("const RETYPE_TYPES=")
    decl = src[i:src.index(";", i)]
    browser = set(decl[decl.index("["):].replace("'", "").replace("[", "")
                  .replace("]", "").replace("\n", "").replace(" ", "").split(","))
    assert browser == set(cityos_main.COLUMN_RETYPE_TYPES), \
        browser.symmetric_difference(set(cityos_main.COLUMN_RETYPE_TYPES))


def test_every_type_the_server_knows_has_a_hebrew_name_on_both_sides():
    """The log line is written on the server and the dialog in the browser;
    a type named in one and not the other reads as a bug in whichever the
    person happens to be looking at."""
    src = INDEX.read_text(encoding="utf-8")
    assert set(cityos_main.COLUMN_TYPE_HE) >= set(cityos_main.COLUMN_RETYPE_TYPES)
    for t in cityos_main.COLUMN_RETYPE_TYPES:
        assert f"{{type:'{t}',he:" in src, t


def test_the_log_line_has_its_own_wording_for_a_retype():
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  fieldLabel(a){"):]
    fn = fn[:fn.index("\n  },")]
    assert "a.action==='update'?'סוג עמודה שונה'" in fn, fn


def test_the_board_is_reloaded_after_the_change():
    """Every cell changed shape. Re-rendering off the loaded items draws the
    column empty, which looks exactly like the conversion having eaten it."""
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("async function doRetypeColumn("):]
    fn = fn[:fn.index("\n}")]
    assert "await refreshBoardItems();" in fn, fn
    assert "confirm_columns" in fn, fn


def test_the_preview_is_shown_before_anything_is_written():
    """The picker opens the plan, and only the plan's own button writes."""
    src = INDEX.read_text(encoding="utf-8")
    pick = src[src.index("function retypeColumn(colId){"):]
    pick = pick[:pick.index("\nfunction colTypeHe")]
    assert "retypePreview(" in pick and "doRetypeColumn(" not in pick, pick


def test_the_menu_offers_it_where_it_can_be_done_and_nowhere_else():
    """Driven harness: tests/frontend/column_retype_menu.mjs.

    Verified to fail: drop the RETYPE_TYPES guard from colMenu and the
    "not offered" cases go red; drop the isAdmin guard and two more do.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "column_retype_menu.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
