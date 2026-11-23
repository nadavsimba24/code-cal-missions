"""A formula whose answer is a number gets a number column's display settings.

Asked for on 2026-11-23: a formula column's menu offers "הגדרות תצוגת מספר" —
the unit (₪, $, free text) and the thousands separator a number column has —
when its result is a number. It is presentation only: evalFormula goes on
answering a number, so sorting, group sums and the export are untouched.

Pinned on both sides. The server used to keep `number` on a number column only
and drop it from every other, so the setting would have vanished at the first
save; and the screen has to offer the entry, honour it in the cell, and not
offer it to a formula that answers with words.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json().get("columns") or []


def test_a_formula_column_keeps_its_unit_and_separator(client, admin_id):
    bid = client.post("/api/boards", json={"name": "נוסחה מעוצבת", "user_id": admin_id}).json()["id"]
    try:
        cols = _cols(client, bid) + [
            {"id": "c_amt", "title": "סכום", "type": "number"},
            {"id": "c_vat", "title": "כולל מע\"מ", "type": "formula", "formula": "{סכום}*1.18",
             "number": {"unit": "₪", "thousands": True}},
            {"id": "c_txt", "title": "טקסט", "type": "text", "number": {"unit": "₪"}},
        ]
        r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": cols})
        assert r.status_code == 200, r.text
        got = {c.get("title"): c for c in r.json()["columns"]}
        assert got["כולל מע\"מ"].get("number") == {"unit": "₪", "thousands": True}, got["כולל מע\"מ"]
        # still only the two kinds that show a figure
        assert not got["טקסט"].get("number"), got["טקסט"]
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={admin_id}")


def test_the_menu_offers_the_settings_only_to_a_formula_that_answers_a_number():
    assert re.search(r"c\.type==='number'\|\|\(c\.type==='formula'&&formulaIsNumeric\(c\)\)", SRC)
    body = SRC.split("function formulaIsNumeric(c){", 1)[1].split("\n}", 1)[0]
    assert "typeof evalFormula(c,t)==='number'" in body
    # a column that already carries the setting can always have it taken off
    assert "if(c.number)return true;" in body


def test_the_cell_draws_a_numeric_result_through_fnum_and_text_as_it_is():
    assert "esc(typeof r==='number'?fnum(r,c):r)" in SRC


def test_evalFormula_still_answers_a_number_so_sorting_is_untouched():
    body = SRC.split("function evalFormula(col,t){", 1)[1].split("\n}", 1)[0]
    assert "fnum(" not in body.replace("_fnum(", "")
