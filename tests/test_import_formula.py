"""Group — bringing a formula across, not only what it worked out.

monday keeps a formula column's definition in the column's own settings, as an
expression over column IDs. This app's formula column reads the same shape over
column TITLES and computes plain arithmetic — so a formula is translated and
then judged: one this app can compute becomes a live formula column, and one it
cannot keeps monday's computed value, with the expression preserved either way.
"""
import json

from sqlalchemy.orm import Session
import main as cityos_main
import import_monday
from models import Board, Task


def _resp(items, columns=None):
    board = {"id": "1", "name": "לוח", "items_page": {"items": items}}
    if columns is not None:
        board["columns"] = columns
    return json.dumps({"data": {"boards": [board]}}).encode()


def _col(cid, title, ctype, formula=None):
    c = {"id": cid, "title": title, "type": ctype}
    if formula is not None:
        c["settings_str"] = json.dumps({"formula": formula, "hide_footer": False})
    return c


def _cv(cid, title, ctype, text="", display_value=None):
    out = {"id": cid, "type": ctype, "column": {"title": title}, "text": text}
    if display_value is not None:
        out["display_value"] = display_value
    return out


def _item(name, cells):
    return {"id": "9" + name, "name": name, "column_values": list(cells)}


def _import(client, admin_id, raw):
    return client.post(f"/api/boards/import?actor_id={admin_id}",
                       files={"file": ("board.json", raw, "application/json")},
                       data={"actor_id": admin_id})


def _cols(board_id):
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        return [c for c in (b.settings or {}).get("columns", []) if c["id"].startswith("col_")]


# ── the translation, on its own ─────────────────────────────────────────────

def test_a_formula_is_translated_from_column_ids_to_titles():
    expr, missing = import_monday.translate_formula(
        "{numeric_1} * 2 + {numeric_2}", {"numeric_1": "שעות", "numeric_2": "תוספת"})
    assert expr == "{שעות} * 2 + {תוספת}"
    assert missing == []


def test_a_reference_to_a_column_that_did_not_come_is_reported():
    expr, missing = import_monday.translate_formula("{a} + {gone}", {"a": "קיימת"})
    assert missing == ["gone"]
    assert "{gone}" in expr, "the untranslatable reference is left visible, not dropped"


def test_the_boundary_is_the_engines_function_table():
    """It used to be "arithmetic only", which froze every IF and ROUND a
    migrated board arrived with. Now the question is whether the engine has the
    function — see tests/test_formula_engine.py for the table itself."""
    ok = ["{שעות} * 2", "({א} + {ב}) / 2", "IF({א} > 2, 1, 0)",
          "CONCATENATE({א}, {ב})", "DAYS(TODAY(), {ב})", "ROUND({א} * 2, 1)"]
    no = ["SWITCH({א}, 1, 2)", "VLOOKUP({א})", "", "   "]
    for e in ok:
        assert import_monday.formula_is_computable(e), e
    for e in no:
        assert not import_monday.formula_is_computable(e), e


# ── end to end ──────────────────────────────────────────────────────────────

def test_an_arithmetic_formula_arrives_as_a_live_formula_column(client, admin_id):
    cols = [_col("n1", "שעות", "numbers"), _col("f1", "כפול שתיים", "formula", "{n1} * 2")]
    cells = [_cv("n1", "שעות", "numbers", text="21"),
             _cv("f1", "כפול שתיים", "formula", text="", display_value="42")]
    d = _import(client, admin_id, _resp([_item("פריט", cells)], cols)).json()
    r = d["report"]
    assert [f["title"] for f in r["formulas_live"]] == ["כפול שתיים"]
    assert r["formulas_live"][0]["formula"] == "{שעות} * 2"

    col = next(c for c in _cols(d["id"]) if c["title"] == "כפול שתיים")
    assert col["type"] == "formula", col
    assert col["formula"] == "{שעות} * 2"
    # the column computes, so no frozen copy of monday's answer is stored beside it
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.board_id == d["id"]).first()
    assert col["id"] not in (t.custom_fields or {}), "monday's snapshot was stored too"


def test_a_formula_this_app_cannot_compute_keeps_mondays_answer(client, admin_id):
    """SWITCH is monday's own and has no counterpart here. Imported as a live
    formula the column would simply show nothing, so the computed value stays."""
    cols = [_col("n1", "ימים", "numbers"),
            _col("f1", "בזמן?", "formula", "SWITCH({n1}, 1, \"כן\", \"לא\")")]
    cells = [_cv("n1", "ימים", "numbers", text="12"),
             _cv("f1", "בזמן?", "formula", display_value="כן")]
    d = _import(client, admin_id, _resp([_item("פריט", cells)], cols)).json()
    r = d["report"]
    assert [f["title"] for f in r["formulas_as_text"]] == ["בזמן?"]
    assert not r["formulas_live"]

    col = next(c for c in _cols(d["id"]) if c["title"] == "בזמן?")
    assert col["type"] == "text"
    # the expression is still there — nobody has to go back to monday to read it
    assert col["formula"] == 'SWITCH({ימים}, 1, "כן", "לא")'
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.board_id == d["id"]).first()
    assert (t.custom_fields or {})[col["id"]] == "כן", "the computed value was lost"


def test_the_mapping_note_says_which_of_the_two_happened(client, admin_id):
    cols = [_col("n1", "שעות", "numbers"),
            _col("f1", "חי", "formula", "{n1} * 2"),
            _col("f2", "קפוא", "formula", "SWITCH({n1}, 1, 2)")]
    cells = [_cv("n1", "שעות", "numbers", text="5"),
             _cv("f1", "חי", "formula", display_value="10"),
             _cv("f2", "קפוא", "formula", display_value="5")]
    d = _import(client, admin_id, _resp([_item("פריט", cells)], cols)).json()
    notes = {m["title"]: (m.get("note") or "") for m in d["report"]["mapping"]}
    assert "מחושבת כאן מחדש" in notes["חי"]
    assert "SWITCH" in notes["קפוא"], notes["קפוא"]


def test_a_file_without_the_column_definitions_still_imports(client, admin_id):
    """The old query did not ask for them. The computed values come across as
    before, and no formula is invented."""
    cells = [_cv("f1", "נוסחה", "formula", display_value="42")]
    d = _import(client, admin_id, _resp([_item("פריט", cells)])).json()
    assert d["report"]["formulas_live"] == [] and d["report"]["formulas_as_text"] == []
    col = next(c for c in _cols(d["id"]) if c["title"] == "נוסחה")
    assert col["type"] == "text" and not col["formula"]
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.board_id == d["id"]).first()
    assert (t.custom_fields or {})[col["id"]] == "42"


def test_the_export_query_asks_for_the_column_definitions():
    import pathlib
    q = (pathlib.Path(__file__).resolve().parent.parent / "backend" / "monday_export.graphql"
         ).read_text(encoding="utf-8")
    assert "columns { id title type settings_str }" in q


def test_the_report_shows_the_formulas_it_brought():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
           ).read_text(encoding="utf-8")
    for marker in ("formulas_live", "formulas_as_text", "מחושבות כאן מחדש",
                   "פונקציה שאינה נתמכת", "עמודה שלא יובאה"):
        assert marker in src, f"the report says nothing about {marker}"
