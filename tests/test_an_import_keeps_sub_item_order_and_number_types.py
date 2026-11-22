"""An imported board keeps its sub-items' column order, and its numbers stay numbers.

Two things a migrated board was getting wrong, both reported on a real board:

1. **Sub-item column order.** monday's sub-item board lists its columns in an
   order of its own — and some of them exist on the parent board too, some only
   on the sub-items. Both importers wrote the shared ones into `sub_cols` and
   left the sub-item-only ones for the board to append after them, so a sub-item
   board whose columns interleave the two came back reshuffled: "Owner, אחראי,
   שעות" in monday read "אחראי, Owner, שעות" here. `sub_cols` now lists every
   sub-item column in the source's order, and the board places a sub-item-only
   column wherever `sub_cols` names it (the frontend half is in
   tests/frontend/sub_cols_only_their_own.mjs).

2. **A number column that arrived as text.** In an Excel file a sub-item column
   was joined to an item column by title alone, so the sub-items' "כמות"
   figures were written into the items' TEXT "כמות" — monday has them as two
   columns of two types, and the JSON import already matched on title AND type.
   And a column whose cells write a unit beside every figure ("3 ימים") was
   read as text, because no cell of it parsed as a bare number.
"""
import json

from sqlalchemy.orm import Session

import main as cityos_main
from models import Board, Task
from test_import_monday_subitem_columns import _board, _cv, _resp, _sub, _upload
from test_import_subitems import _imp, _sheet


def _settings(bid):
    with Session(cityos_main.engine) as db:
        return dict(db.query(Board).filter(Board.id == bid).first().settings or {})


def _sub_titles(s):
    titles = {c["id"]: c["title"] for c in s.get("columns", [])}
    return [titles.get(i, i) for i in (s.get("sub_cols") or [])[1:]]


def _kid(bid):
    with Session(cityos_main.engine) as db:
        return (db.query(Task).filter(Task.board_id == bid, Task.parent_id.isnot(None))
                .order_by(Task.id).first())


# ── 1. the sub-item board's own order ───────────────────────────────────────

def test_a_monday_file_keeps_the_sub_item_boards_order_with_its_own_columns_between(client):
    raw = _resp([{"id": "1", "name": "תיקון מדרכה",
                  "column_values": [_cv("text0", "אחראי", "text", text="דנה")],
                  # a sub-item-only column FIRST, the shared one in the middle
                  "subitems": [_sub("פירוק", [
                      _cv("person", "Owner", "text", text="יואב"),
                      _cv("text7", "אחראי", "text", text="רון"),
                      _cv("numbers4", "שעות", "numbers", text="12", value="12")])]}])
    r = _upload(client, raw, name="סדר תתי פריטים")
    assert r.status_code == 200, r.text
    s = _settings(r.json()["id"])
    assert _sub_titles(s) == ["Owner", "אחראי", "שעות"], _sub_titles(s)


def test_an_excel_file_keeps_the_bands_order_with_its_own_columns_between(client, admin_id):
    raw = _sheet(
        [["פריט", "אחראי"],
         ["תיקון מדרכה", "דנה"],
         ["", "פריט", "קבלן", "אחראי", "שלב"],
         ["", "פירוק", "כהן", "יואב", "הכנה"]],
        bands={2}, levels={1: 1, 2: 2, 3: 2})
    r = _imp(client, admin_id, raw)
    assert r.status_code == 200, r.text
    s = _settings(r.json()["id"])
    assert _sub_titles(s) == ["קבלן", "אחראי", "שלב"], _sub_titles(s)
    titles = {c["id"]: c["title"] for c in s["columns"]}
    assert sorted(titles[i] for i in s["sub_only"]) == sorted(["קבלן", "שלב"])


# ── 2. numbers stay numbers ─────────────────────────────────────────────────

def test_a_sub_item_number_column_is_not_poured_into_an_item_text_column_of_the_same_name(
        client, admin_id):
    raw = _sheet(
        [["פריט", "כמות"],
         ["תיקון מדרכה", "הרבה"],
         ["", "פריט", "כמות"],
         ["", "פירוק", "12"],
         ["", "יציקה", "7.5"]],
        bands={2}, levels={1: 1, 2: 2, 3: 2, 4: 2})
    r = _imp(client, admin_id, raw)
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    s = _settings(bid)
    cols = [c for c in s["columns"] if c["title"] == "כמות"]
    assert sorted(c["type"] for c in cols) == ["number", "text"], cols
    num = next(c for c in cols if c["type"] == "number")
    assert num["id"] in s["sub_only"]
    assert (_kid(bid).custom_fields or {}).get(num["id"]) == 12


def test_a_column_that_writes_its_unit_in_every_cell_is_a_number_column(client, admin_id):
    raw = _sheet(
        [["פריט", "משך", "שלב"],
         ["א", "3 ימים", "שלב 1"],
         ["ב", "12 ימים", "שלב 2"]])
    r = _imp(client, admin_id, raw)
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    s = _settings(bid)
    by = {c["title"]: c for c in s["columns"]}
    assert by["משך"]["type"] == "number", by["משך"]
    assert (by["משך"].get("number") or {}).get("unit") == "ימים"
    # a word BEFORE the figure is a name, not a unit
    assert by["שלב"]["type"] == "text"
    with Session(cityos_main.engine) as db:
        vals = sorted((t.custom_fields or {}).get(by["משך"]["id"])
                      for t in db.query(Task).filter(Task.board_id == bid).all())
    assert vals == [3, 12]


def test_cells_that_disagree_about_the_unit_stay_text():
    assert cityos_main._imp_infer_type(["3 ימים", "4 שעות"]) == "text"
    assert cityos_main._imp_infer_type(["10:30", "11:00"]) == "text"
    assert cityos_main._imp_infer_type(["054-1234567"]) == "text"
    assert cityos_main._imp_infer_type(["3 ימים", "5"]) == "number"
    # a remark beside a figure is not a unit, and one unit among plain figures
    # is not the unit of the whole column
    assert cityos_main._imp_infer_type(["12", "16", "18+"]) == "text"
    assert cityos_main._imp_infer_type(["5", "8", "7 ?"]) == "text"
    assert cityos_main._imp_number_unit(["5", "8", "3 ימים"]) is None
    assert cityos_main._imp_number_unit(["12 מ\"ר", "40 מ\"ר"]) == 'מ"ר'


def test_number_columns_with_different_units_are_not_one_column(client, admin_id):
    raw = _sheet(
        [["פריט", "משך"],
         ["תיקון מדרכה", "3 ימים"],
         ["", "פריט", "משך"],
         ["", "פירוק", "4 שעות"]],
        bands={2}, levels={1: 1, 2: 2, 3: 2})
    r = _imp(client, admin_id, raw)
    assert r.status_code == 200, r.text
    cols = [c for c in _settings(r.json()["id"])["columns"] if c["title"] == "משך"]
    assert sorted((c.get("number") or {}).get("unit") for c in cols) == ["ימים", "שעות"], cols


def test_a_file_whose_name_has_a_comma_is_still_one_file():
    """monday writes a file's name into its address unescaped, and a cell holds
    several addresses comma-joined. Split on every comma, a name like "אספקה,
    התקנה.docx" broke the cell into pieces that are not addresses — the column
    read as text, and once a sub-item column is joined to an item column only
    when the types agree, it would have split off as a second column too."""
    a = "https://x.monday.com/protected_static/1/resources/2/אספקה, התקנה ושיפוץ.docx"
    b = "https://x.monday.com/protected_static/1/resources/3/4.svg"
    assert cityos_main._imp_asset_urls(f"{a}, {b}") == [a, b]
    assert cityos_main._imp_infer_type([a, f"{a}, {b}"]) == "files"
    # and an ordinary sentence with a comma in it is still no file at all
    assert cityos_main._imp_asset_urls("שלום, עולם") is None


def test_a_monday_number_whose_text_carries_its_unit_is_still_the_number(client):
    raw = json.dumps({"data": {"boards": [{
        "name": "יחידות",
        "columns": [{"id": "numbers0", "title": "משך", "type": "numbers",
                     "settings_str": json.dumps({"unit": {"symbol": "custom",
                                                          "custom_unit": "ימים",
                                                          "direction": "right"}})}],
        "items_page": {"cursor": None, "items": [
            {"id": "1", "name": "א",
             "column_values": [_cv("numbers0", "משך", "numbers", text="27 ימים", value='"27"')]},
            {"id": "2", "name": "ב",
             "column_values": [_cv("numbers0", "משך", "numbers", text="4 ימים")]}]}}]}},
        ensure_ascii=False).encode()
    r = _upload(client, raw, name="יחידות")
    assert r.status_code == 200, r.text
    board = _board(client, r.json()["id"])
    col = next(c for c in board["columns"] if c["title"] == "משך")
    assert col["type"] == "number"
    assert (col.get("number") or {}).get("unit") == "ימים"
    got = sorted(t["custom_fields"].get(col["id"]) for t in board["tasks"])
    assert got == [4, 27], got
