"""Group — sub-items a file names and does not spell out.

monday writes its sub-items twice. Once as rows of their own: a band naming
their columns, and under it a row per sub-item carrying its values. And once as
their NAMES, joined by commas, in the item's sub-items column — which is not a
column of values at all, it IS the sub-items.

A file exported without the rows still carries that column. monday's CSV export
of a board writes only the names; so does an Excel export taken with the
sub-items collapsed; and so does an API response from a query that never asked
for `subitems`. In every one of those the file plainly says which sub-items
exist, and the import created none of them — while the report said that column
"יובא כתתי־פריטים של הפריטים עצמם", which is the loss named as the feature.
Her board came across with its sub-items missing and a report claiming they had
arrived.

So the names become sub-items. A name is not the sub-item — there are no
columns behind it and no conversation — and everything here is about keeping
those two apart: the rows win wherever the file has them, nothing is created
twice, and the report says which of the two this board got.
"""
import io
import json

from openpyxl import Workbook
from sqlalchemy.orm import Session

import import_monday
import main as cityos_main
from models import Task

H = {"X-CityOS-User": "1", "host": "localhost"}


# ── files ──────────────────────────────────────────────────────────────────
def _cv(cid, title, ctype, text=""):
    return {"id": cid, "type": ctype, "column": {"title": title}, "text": text}


def _item(name, subitems_text=None, subitems=None, cols=()):
    """An item as monday answers it. `subitems_text` is the sub-items column —
    the names, comma-joined — and `subitems` the rows themselves."""
    cvs = list(cols)
    if subitems_text is not None:
        cvs.append(_cv("subitems", "Subitems", "subtasks", subitems_text))
    it = {"id": str(abs(hash(name)) % 10000), "name": name,
          "group": {"id": "g1", "title": "קבוצה"}, "column_values": cvs}
    if subitems is not None:
        it["subitems"] = subitems
    return it


def _resp(items):
    board = {"name": "ניהול תוכן", "groups": [{"id": "g1", "title": "קבוצה"}],
             "items_page": {"cursor": None, "items": items}}
    return json.dumps({"data": {"boards": [board]}}, ensure_ascii=False).encode()


def _monday_sheet(rows, header=("Name", "Subitems", "מטפל"), band_rows=()):
    """monday's Excel layout: the board's name, a group, the header, the items
    — and, where `band_rows` says so, a sub-item band with its rows."""
    wb = Workbook()
    ws = wb.active
    ws.append(["ניהול תוכן אתר החברה"])
    ws.append(["עליה לאוויר - יוני"])
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
        for sub in band_rows:
            if sub[0] == r[0]:
                ws.append([header[1], header[0]] + list(header[2:]))
                for name in sub[1]:
                    ws.append(["", name] + [""] * (len(header) - 2))
                break
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _imp(client, raw, filename="board.xlsx"):
    r = client.post("/api/boards/import",
                    files={"file": (filename, raw, "application/octet-stream")},
                    data={}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def _tree(board_id):
    """{item title: [sub-item titles]} — the board as a hierarchy."""
    with Session(cityos_main.engine) as db:
        ts = db.query(Task).filter(Task.board_id == board_id).order_by(Task.id).all()
    by_id = {t.id: t for t in ts}
    out = {t.title: [] for t in ts if not t.parent_id}
    for t in ts:
        if t.parent_id:
            out.setdefault(by_id[t.parent_id].title, []).append(t.title)
    return out


# ── reading the names out of the cell ──────────────────────────────────────
def test_the_names_are_split_on_the_comma_monday_joins_them_with():
    assert import_monday._subitem_names(
        _item("פריט", "הפרויקטים שלנו, צור קשר, אודות"), {"subitems"}) == [
        "הפרויקטים שלנו", "צור קשר", "אודות"]


def test_an_empty_sub_items_cell_names_nobody():
    assert import_monday._subitem_names(_item("פריט", ""), {"subitems"}) == []
    assert import_monday._subitem_names(_item("פריט", " , ,  "), {"subitems"}) == []


def test_a_column_that_is_not_the_sub_items_one_is_not_read_as_names():
    it = _item("פריט", cols=[_cv("t", "הערה", "text", "א, ב, ג")])
    assert import_monday._subitem_names(it, {"subitems"}) == []


def test_the_names_of_one_item_have_a_ceiling():
    """A cell is not an unbounded list — past this it is not a sub-item list."""
    many = ", ".join(f"תת {i}" for i in range(import_monday.SUBITEM_NAMES_MAX + 40))
    got = import_monday._subitem_names(_item("פריט", many), {"subitems"})
    assert len(got) == import_monday.SUBITEM_NAMES_MAX


# ── a monday API response ──────────────────────────────────────────────────
def test_a_response_that_never_asked_for_subitems_still_brings_them(client):
    """The query asked for the items and not for their sub-items. The sub-items
    column names them, and that is the file saying they exist."""
    d = _imp(client, _resp([_item("דף הבית", "הפרויקטים שלנו, צור קשר"),
                            _item("טפסים", "טופס א")]), filename="response.json")
    assert _tree(d["id"]) == {"דף הבית": ["הפרויקטים שלנו", "צור קשר"],
                              "טפסים": ["טופס א"]}
    assert d["subitems"] == 3
    assert d["report"]["subitems_named"] == 3


def test_the_rows_win_wherever_the_file_has_them(client):
    """A sub-item row carries its values; the column carries the same names a
    second time. Read as well as the rows, every sub-item would arrive twice."""
    subs = [{"id": "201", "name": "הפרויקטים שלנו",
             "column_values": [_cv("st", "מטפל", "text", "דנה")]},
            {"id": "202", "name": "צור קשר",
             "column_values": [_cv("st", "מטפל", "text", "רינה")]}]
    d = _imp(client, _resp([_item("דף הבית", "הפרויקטים שלנו, צור קשר", subitems=subs)]),
             filename="response.json")
    assert _tree(d["id"]) == {"דף הבית": ["הפרויקטים שלנו", "צור קשר"]}
    assert d["report"]["subitems_named"] == 0


def test_a_sub_item_built_from_a_name_carries_the_name_and_says_so(client):
    """It has no columns behind it — the file holds none — and the report says
    that, so "3 תתי־פריטים" is not read as three that came across whole."""
    d = _imp(client, _resp([_item("דף הבית", "צור קשר")]), filename="response.json")
    with Session(cityos_main.engine) as db:
        sub = db.query(Task).filter(Task.board_id == d["id"],
                                    Task.parent_id.isnot(None)).one()
        assert sub.title == "צור קשר"
        assert set(sub.custom_fields or {}) <= {"status_unset", "priority_unset"}
    assert d["report"]["subitems_named"] == d["report"]["subitems"] == 1


def test_an_item_with_no_sub_items_named_gets_none(client):
    d = _imp(client, _resp([_item("דף הבית", ""), _item("טפסים", "טופס א")]),
             filename="response.json")
    assert _tree(d["id"]) == {"דף הבית": [], "טפסים": ["טופס א"]}


def test_the_sub_items_column_is_still_not_a_column_of_the_board(client):
    """It is the sub-items, not a cell of text beside them — read as a column
    it would stand on every item holding their names a second time."""
    d = _imp(client, _resp([_item("דף הבית", "צור קשר")]), filename="response.json")
    board = client.get(f"/api/boards/{d['id']}?user_id=1", headers=H).json()
    assert "Subitems" not in [c.get("title") for c in board["columns"]]
    assert d["report"]["as_subitems"] == ["Subitems"]


# ── monday's own spreadsheet export ────────────────────────────────────────
def test_a_sheet_that_names_its_sub_items_and_has_no_rows_for_them(client):
    d = _imp(client, _monday_sheet([["דף הבית", "הפרויקטים שלנו, צור קשר", "רינה"],
                                    ["טפסים", "טופס א, טופס ב", "דנה"]]))
    assert _tree(d["id"]) == {"דף הבית": ["הפרויקטים שלנו", "צור קשר"],
                              "טפסים": ["טופס א", "טופס ב"]}
    assert d["report"]["subitems_named"] == 4


def test_a_csv_names_them_the_same_way(client):
    """monday's CSV export has no rows for sub-items at all — the column is the
    only place they appear, and it is the common case."""
    csv = ("ניהול תוכן אתר החברה\nעליה לאוויר - יוני\nName,Subitems,מטפל\n"
           "דף הבית,\"הפרויקטים שלנו, צור קשר\",רינה\n")
    d = _imp(client, csv.encode(), filename="board.csv")
    assert _tree(d["id"]) == {"דף הבית": ["הפרויקטים שלנו", "צור קשר"]}
    assert d["report"]["subitems_named"] == 2


def test_the_rows_in_a_sheet_win_over_the_names_beside_them(client):
    """The band and its rows are in the file, and the column repeats their
    names. Only one of the two becomes sub-items."""
    d = _imp(client, _monday_sheet([["דף הבית", "הפרויקטים שלנו, צור קשר", "רינה"]],
                                   band_rows=[("דף הבית", ["הפרויקטים שלנו", "צור קשר"])]))
    assert _tree(d["id"]) == {"דף הבית": ["הפרויקטים שלנו", "צור קשר"]}
    assert d["report"]["subitems_named"] == 0


def test_one_item_with_rows_does_not_cost_another_item_its_names(client):
    """The file spelled out one item's sub-items and only named the other's.
    Both end up with theirs."""
    d = _imp(client, _monday_sheet([["דף הבית", "הפרויקטים שלנו", "רינה"],
                                    ["טפסים", "טופס א, טופס ב", "דנה"]],
                                   band_rows=[("דף הבית", ["הפרויקטים שלנו"])]))
    assert _tree(d["id"]) == {"דף הבית": ["הפרויקטים שלנו"],
                              "טפסים": ["טופס א", "טופס ב"]}
    assert d["report"]["subitems_named"] == 2


def test_a_sub_item_lands_in_its_parents_group(client):
    """A sub-item belongs to the item, and the item belongs to a group. Filed
    anywhere else it shows up as a loose row of a group it never was in."""
    d = _imp(client, _monday_sheet([["דף הבית", "צור קשר", "רינה"]]))
    with Session(cityos_main.engine) as db:
        parent = db.query(Task).filter(Task.board_id == d["id"],
                                       Task.parent_id.is_(None)).one()
        sub = db.query(Task).filter(Task.board_id == d["id"],
                                    Task.parent_id.isnot(None)).one()
        assert sub.group_id == parent.group_id


def test_the_board_hands_the_sub_items_back_under_their_item(client):
    """Through the real board endpoint — a sub-item in the database and not on
    the board is the same missing sub-item from where anybody is looking."""
    d = _imp(client, _monday_sheet([["דף הבית", "הפרויקטים שלנו, צור קשר", "רינה"]]))
    board = client.get(f"/api/boards/{d['id']}?user_id=1", headers=H).json()
    item, = [t for t in board["tasks"]]
    assert [s["title"] for s in (item.get("subtasks") or [])] == [
        "הפרויקטים שלנו", "צור קשר"]


def test_a_nameless_row_is_not_read_as_an_item_with_sub_items(client):
    """A row with an empty first cell and a name in its second is a sub-item
    whose band went unread — that second cell is its OWN name. Read as a list
    of sub-items it became a sub-item hanging off a nameless item."""
    d = _imp(client, _monday_sheet([["פריט א", "", "רינה"],
                                    ["", "שורה עם שם בתא השני", "דנה"]]))
    assert d["report"]["subitems_named"] == 0
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.board_id == d["id"],
                                     Task.parent_id.isnot(None)).count() == 0


# ── the report ─────────────────────────────────────────────────────────────
def test_the_report_tells_a_name_apart_from_a_sub_item():
    """Driven harness: tests/frontend/import_subitems_named.mjs. The old line
    said the column "was imported as the items' sub-items" over a board that
    got none, which is the one shape of report nobody can catch."""
    import pathlib
    import shutil
    import subprocess

    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = pathlib.Path(__file__).resolve().parent / "frontend" / "import_subitems_named.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
