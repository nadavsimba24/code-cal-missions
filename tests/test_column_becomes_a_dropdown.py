"""המרת עמודה קיימת לרשימה נפתחת — והערכים שכבר בה הם האפשרויות.

A board admin could always retype a column: the board PATCH takes a full
replacement of the column definitions, and a text column named as a dropdown
in that payload becomes one. What it could never do is the half that matters.
That branch replaces DEFINITIONS and never touches a cell, so the column
arrived as a list with an empty vocabulary and every answer already written
into it unreadable — a dropdown cell is a LIST of option strings, and ninety
cells holding the bare string "תשתיות" render as ninety empty cells.

Which is backwards from what anybody wants. The column already holds the
list; somebody typed it out by hand a hundred times. The declaration is the
part that is missing. So POST .../columns/{id}/dropdown moves both together,
in one transaction, and the GET on the same path says what it would do
before it does it.

What is pinned here:

  · the options are the values the column actually holds, and the cells keep
    those values — the shape changes, the content does not
  · items in the recycle bin are converted too. A cell left in the old shape
    is a wrong cell the day somebody restores the item, and a restore is the
    worst possible place to discover it
  · a status column keeps the order and the full vocabulary its admin chose,
    unused options included — those are the column's list whether or not
    anyone has picked them yet
  · only a board admin, only from a type that holds a value a list can be
    made out of, and never past DROPDOWN_CONVERT_MAX distinct values
  · a form that asks about the column has to be agreed to out loud, the same
    409 bargain the board PATCH strikes for a retype
  · the board's log says the type changed, and does not say it was deleted
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


# ── the conversion itself ───────────────────────────────────────────────────

def test_the_values_in_the_column_become_the_list(client, admin_id):
    """The whole of the feature on one board: what was typed is now offered."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    for t, v in [("א", "תשתיות"), ("ב", "חינוך"), ("ג", "תשתיות"), ("ד", "")]:
        _item(client, admin_id, bid, t, cid, v)

    plan = client.get(f"/api/boards/{bid}/columns/{cid}/dropdown?user_id={admin_id}")
    assert plan.status_code == 200, plan.text
    plan = plan.json()
    # counted on the server, so the dialog can say how much it touches, and
    # sorted — a text column has no order of its own to preserve
    assert [(o["value"], o["count"]) for o in plan["options"]] == \
        [("חינוך", 1), ("תשתיות", 2)]
    assert plan["cells"] == 3 and plan["type"] == "text"
    assert plan["too_many"] is False

    r = client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                    json={"user_id": admin_id})
    assert r.status_code == 200, r.text
    assert r.json()["options"] == ["חינוך", "תשתיות"]

    col = _coldef(client, admin_id, bid, cid)
    assert col["type"] == "dropdown"
    assert col["options"] == ["חינוך", "תשתיות"]
    # the content is what it was; only the shape moved
    assert _cells(client, admin_id, bid, cid, "אבגד") == {
        "א": ["תשתיות"], "ב": ["חינוך"], "ג": ["תשתיות"], "ד": None}


def test_a_cell_in_the_recycle_bin_is_converted_too(client, admin_id):
    """Otherwise the restore is where the old shape surfaces, weeks later and
    as a cell that silently reads empty."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    live = _item(client, admin_id, bid, "חי", cid, "תברואה")
    binned = _item(client, admin_id, bid, "בסל", cid, "רווחה")
    assert client.delete(f"/api/tasks/{binned}?user_id={admin_id}").status_code == 200

    # the value of a binned item still counts towards the vocabulary: it is a
    # value the column holds, and the item can come back
    plan = client.get(f"/api/boards/{bid}/columns/{cid}/dropdown?user_id={admin_id}").json()
    assert [o["value"] for o in plan["options"]] == ["רווחה", "תברואה"]

    assert client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                       json={"user_id": admin_id}).status_code == 200
    r = client.post(f"/api/tasks/{binned}/restore", json={"user_id": admin_id})
    assert r.status_code == 200, r.text
    assert _cells(client, admin_id, bid, cid, ("חי", "בסל")) == {
        "חי": ["תברואה"], "בסל": ["רווחה"]}
    assert live  # the live one is the control


def test_a_status_column_keeps_the_vocabulary_its_admin_wrote(client, admin_id):
    """A status column already HAS a list, in an order somebody chose. Sorting
    it would scramble that, and dropping the options nobody has picked yet
    would quietly delete the admin's work."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="status", title="שלב",
               options=[{"label": "תכנון", "color": "#0073ea"},
                        {"label": "ביצוע", "color": "#00c875"},
                        {"label": "אחזקה", "color": "#fdab3d"}])["id"]
    opts = _coldef(client, admin_id, bid, cid)["options"]
    pick = {o["label"]: o for o in opts}
    _item(client, admin_id, bid, "א", cid, pick["ביצוע"])
    _item(client, admin_id, bid, "ב", cid, pick["תכנון"])

    plan = client.get(f"/api/boards/{bid}/columns/{cid}/dropdown?user_id={admin_id}").json()
    # the declared order, not alphabetical — and אחזקה survives at nought uses
    assert [(o["value"], o["count"]) for o in plan["options"]] == \
        [("תכנון", 1), ("ביצוע", 1), ("אחזקה", 0)]

    assert client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                       json={"user_id": admin_id}).status_code == 200
    assert _coldef(client, admin_id, bid, cid)["options"] == ["תכנון", "ביצוע", "אחזקה"]
    # the cell held a snapshot of the option; it now holds the label
    assert _cells(client, admin_id, bid, cid, "אב") == {"א": ["ביצוע"], "ב": ["תכנון"]}


def test_a_number_column_reads_like_the_figure_did(client, admin_id):
    """3 and not 3.0 — an option that does not read like the cell did is a
    value somebody has to recognise twice."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="number", title="אזור")["id"]
    _item(client, admin_id, bid, "א", cid, 3)
    _item(client, admin_id, bid, "ב", cid, 12.5)
    assert client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                       json={"user_id": admin_id}).status_code == 200
    assert _coldef(client, admin_id, bid, cid)["options"] == ["12.5", "3"]
    assert _cells(client, admin_id, bid, cid, "אב") == {"א": ["3"], "ב": ["12.5"]}


def test_an_empty_column_converts_to_an_empty_list(client, admin_id):
    """Not refused: declaring the column a list before anybody fills it in is
    a reasonable thing to want, and the options can be added by hand."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    _item(client, admin_id, bid, "א")
    r = client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                    json={"user_id": admin_id})
    assert r.status_code == 200, r.text
    assert r.json()["options"] == []
    assert _coldef(client, admin_id, bid, cid)["type"] == "dropdown"


# ── what it refuses ─────────────────────────────────────────────────────────

def test_only_a_board_admin_may_convert(client, admin_id, member_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    assert client.post(f"/api/boards/{bid}/members",
                       json={"user_id": admin_id, "member_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    for call in (lambda: client.get(f"/api/boards/{bid}/columns/{cid}/dropdown"
                                    f"?user_id={member_id}"),
                 lambda: client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                                     json={"user_id": member_id})):
        assert call().status_code == 403
    # and it really did not happen
    assert _coldef(client, admin_id, bid, cid)["type"] == "text"


def test_a_type_with_no_vocabulary_behind_it_is_refused(client, admin_id):
    """A date, a person or a derived column is not a list waiting to be
    declared — converting one would be throwing the cells away."""
    bid = _board(client, admin_id)
    for t in ("date", "people", "files", "created_at", "item_id"):
        cid = _col(client, admin_id, bid, type=t, title=t)["id"]
        r = client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                        json={"user_id": admin_id})
        assert r.status_code == 400, (t, r.status_code, r.text)
        assert client.get(f"/api/boards/{bid}/columns/{cid}/dropdown"
                          f"?user_id={admin_id}").status_code == 400


def test_a_column_that_is_already_a_list_is_refused(client, admin_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="dropdown", title="תחום",
               options=["א", "ב"])["id"]
    r = client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                    json={"user_id": admin_id})
    assert r.status_code == 400, r.text
    assert _coldef(client, admin_id, bid, cid)["options"] == ["א", "ב"]


def test_a_missing_board_or_column_is_404(client, admin_id):
    bid = _board(client, admin_id)
    assert client.post(f"/api/boards/{bid}/columns/col_nope/dropdown",
                       json={"user_id": admin_id}).status_code == 404
    assert client.post("/api/boards/99999999/columns/col_x/dropdown",
                       json={"user_id": admin_id}).status_code == 404


def test_a_missing_body_is_422_not_500(client, admin_id):
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    assert client.post(f"/api/boards/{bid}/columns/{cid}/dropdown"
                       f"?user_id={admin_id}").status_code == 422


def test_too_many_distinct_values_is_refused_with_the_count(client, admin_id):
    """A list nobody can scroll is not a list, and keeping the first two
    hundred would empty the cells of everybody below the cut."""
    cap = cityos_main.DROPDOWN_CONVERT_MAX
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="חופשי")["id"]
    for i in range(cap + 1):
        _item(client, admin_id, bid, f"פריט {i}", cid, f"ערך {i}")
    plan = client.get(f"/api/boards/{bid}/columns/{cid}/dropdown"
                      f"?user_id={admin_id}").json()
    assert plan["too_many"] is True and len(plan["options"]) == cap + 1
    r = client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                    json={"user_id": admin_id})
    assert r.status_code == 400, r.text
    assert str(cap + 1) in r.json()["detail"], r.json()
    assert _coldef(client, admin_id, bid, cid)["type"] == "text"


# ── the promises a retype owes ──────────────────────────────────────────────

def test_a_form_asking_about_the_column_has_to_be_agreed_to(client, admin_id):
    """The same bargain the board PATCH strikes, in the same 409 shape — the
    browser has one handler for both."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    _item(client, admin_id, bid, "א", cid, "תשתיות")
    me = {"X-CityOS-User": str(admin_id)}
    fid = client.post(f"/api/boards/{bid}/forms", json={}, headers=me).json()["id"]
    q = client.post(f"/api/forms/{fid}/components",
                    json={"kind": "question", "field_key": cid, "label": "תחום"},
                    headers=me)
    assert q.status_code == 200, q.text
    assert client.patch(f"/api/forms/{fid}", json={"status": "PUBLISHED"},
                        headers=me).status_code == 200

    r = client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                    json={"user_id": admin_id})
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert [c["col_id"] for c in d["columns"]] == [cid]
    assert d["columns"][0]["new_type"] == "dropdown"
    assert d["columns"][0]["removed"] is False
    assert d["columns"][0]["forms"], d
    # refused means refused: nothing was written
    assert _coldef(client, admin_id, bid, cid)["type"] == "text"

    ok = client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                     json={"user_id": admin_id, "confirm_columns": [cid]})
    assert ok.status_code == 200, ok.text
    assert _coldef(client, admin_id, bid, cid)["type"] == "dropdown"


def test_the_board_log_says_the_type_changed_and_not_that_it_was_deleted(
        client, admin_id):
    """A line reading "עמודה נמחקה" about a column still on the board is the
    one kind of log entry nobody can check."""
    bid = _board(client, admin_id)
    cid = _col(client, admin_id, bid, type="text", title="תחום")["id"]
    _item(client, admin_id, bid, "א", cid, "תשתיות")
    assert client.post(f"/api/boards/{bid}/columns/{cid}/dropdown",
                       json={"user_id": admin_id}).status_code == 200

    rows = client.get(f"/api/boards/{bid}/activity?user_id={admin_id}")
    assert rows.status_code == 200, rows.text
    hit = [r for r in rows.json()["activity"]
           if r["field"] == "column" and r["action"] == "update"]
    assert len(hit) == 1, rows.json()["activity"]
    assert hit[0]["old"] == "תחום"
    assert "רשימה נפתחת" in hit[0]["new"]
    # a board row opens nothing and can never be undone
    assert hit[0]["task_id"] is None and hit[0]["can_undo"] is False


# ── the browser's half ──────────────────────────────────────────────────────

def test_the_two_lists_of_convertible_types_agree():
    """The menu decides whether to OFFER the entry and the server decides
    whether to allow it. A type in one and not the other is either a menu item
    that always fails, or a conversion nobody can reach."""
    src = INDEX.read_text(encoding="utf-8")
    line = src[src.index("const DROPDOWN_SOURCES="):]
    line = line[:line.index("\n")]
    browser = set(line[line.index("["):line.index("]")].replace("'", "")
                  .replace("[", "").split(","))
    assert browser == set(cityos_main.DROPDOWN_SOURCE_TYPES), \
        browser.symmetric_difference(set(cityos_main.DROPDOWN_SOURCE_TYPES))


def test_the_log_line_has_its_own_wording_for_a_retype():
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  fieldLabel(a){"):]
    fn = fn[:fn.index("\n  },")]
    assert "a.action==='update'?'סוג עמודה שונה'" in fn, fn


def test_the_menu_offers_it_where_it_can_be_done_and_nowhere_else():
    """Driven harness: tests/frontend/column_to_dropdown_menu.mjs.

    Verified to fail: drop the DROPDOWN_SOURCES guard from colMenu and the
    five "not offered" cases go red; drop the isAdmin guard and two more do.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "column_to_dropdown_menu.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_board_is_reloaded_after_the_conversion():
    """Every cell changed shape. Re-rendering off the loaded items draws the
    column empty, which looks exactly like the conversion having eaten it."""
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("async function doConvertColToDropdown("):]
    fn = fn[:fn.index("\n}")]
    assert "await refreshBoardItems();" in fn, fn
    assert "confirm_columns" in fn, fn
