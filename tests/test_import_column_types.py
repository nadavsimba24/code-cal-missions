"""A sheet's column keeps its type on the way in (סוג העמודה בייבוא).

A file import has no column types to read — a spreadsheet lost them when it was
written — so each column is typed from its values, and a column is a number or
a date only if every one of its cells reads as one. Two things made perfectly
good columns fail that test and arrive as text:

* a date cell is read as text before it is typed, and the datetime's own str()
  is "2024-01-24 00:00:00" — a time no date format accepted. Every date column
  of a monday Excel export came across as text.
* a number written for people — "₪1,200", "35%", a no-break-space thousands
  separator — failed float(), and one such cell sank its whole column.

A text column in the wrong type is not cosmetic: it cannot be summed, sorted by
value, filtered by range or driven by a date automation.
"""
import datetime as dt
import io

from sqlalchemy.orm import Session
import main as cityos_main
from models import Board, Task


def _xlsx(rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _import(client, admin_id, raw):
    r = client.post(f"/api/boards/import?actor_id={admin_id}",
                    files={"file": ("types.xlsx", raw,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    data={"actor_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _columns_and_cells(board_id):
    with Session(cityos_main.engine) as db:
        b = db.get(Board, board_id)
        cols = {c["title"]: c for c in (b.settings or {}).get("columns", [])}
        tasks = {t.title: (t.custom_fields or {})
                 for t in db.query(Task).filter(Task.board_id == board_id).all()}
    return cols, tasks


def _cleanup(client, admin_id, board_id):
    client.delete(f"/api/boards/{board_id}?actor_id={admin_id}")


def test_a_column_of_real_date_cells_imports_as_a_date_column(client, admin_id):
    raw = _xlsx([["שם", "תאריך יעד"],
                 ["א", dt.datetime(2024, 1, 24)],
                 ["ב", dt.datetime(2024, 3, 7, 0, 0, 0)]])
    bid = _import(client, admin_id, raw)
    try:
        cols, cells = _columns_and_cells(bid)
        col = cols["תאריך יעד"]
        assert col["type"] == "date"
        assert cells["א"][col["id"]] == "2024-01-24"
        assert cells["ב"][col["id"]] == "2024-03-07"
    finally:
        _cleanup(client, admin_id, bid)


def test_a_date_written_with_a_time_of_day_still_reads_as_that_date():
    assert cityos_main._imp_to_date_iso("2024-01-24 00:00:00") == "2024-01-24"
    assert cityos_main._imp_to_date_iso("2024-01-24T13:05:00") == "2024-01-24"
    assert cityos_main._imp_to_date_iso("24/01/2024 09:30") == "2024-01-24"


def test_a_number_column_written_with_currency_percent_and_separators_stays_a_number(client, admin_id):
    raw = _xlsx([["שם", "תקציב", "אחוז"],
                 ["א", "₪1,200", "35%"],
                 ["ב", "2 500 ₪", "7.5%"],
                 ["ג", 300, "−10%"]])
    bid = _import(client, admin_id, raw)
    try:
        cols, cells = _columns_and_cells(bid)
        budget, pct = cols["תקציב"], cols["אחוז"]
        assert budget["type"] == "number"
        assert pct["type"] == "number"
        assert [cells[n][budget["id"]] for n in "אבג"] == [1200, 2500, 300]
        assert [cells[n][pct["id"]] for n in "אבג"] == [35, 7.5, -10]
    finally:
        _cleanup(client, admin_id, bid)


def test_words_float_would_accept_are_not_mistaken_for_numbers():
    for word in ("inf", "nan", "1e5", "-", ".", "12 34", "050-1234567"):
        assert cityos_main._imp_to_number(word) is None, word


def test_a_column_with_one_real_word_among_numbers_stays_text(client, admin_id):
    # the all-or-nothing rule itself is unchanged: a word in the column is data
    # a number column would throw away
    raw = _xlsx([["שם", "כמות"], ["א", 5], ["ב", "לא ידוע"]])
    bid = _import(client, admin_id, raw)
    try:
        cols, cells = _columns_and_cells(bid)
        assert cols["כמות"]["type"] == "text"
        assert cells["ב"][cols["כמות"]["id"]] == "לא ידוע"
    finally:
        _cleanup(client, admin_id, bid)
