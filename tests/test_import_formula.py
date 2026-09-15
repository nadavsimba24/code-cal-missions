"""Group — bringing a formula across, not only what it worked out.

monday keeps a formula column's definition in the column's own settings, as an
expression over column IDs. This app's formula column reads the same shape over
column TITLES, so the expression is translated and kept on the column.

The column itself arrives as TEXT, holding the value monday computed. That is
the rule the migration is held to: a live formula recomputes from the columns
that made the trip, and one column left behind turns it into a different number
with nothing said. The expression is reachable in the column menu, which offers
turning the column live once someone has looked at the numbers — per column,
deliberately, and reversibly.
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

def test_a_formula_column_arrives_as_text_holding_the_computed_value(client, admin_id):
    """Even one this app could compute perfectly well: 21 * 2 is 42 here too,
    and the board is still made to show the 42 monday showed."""
    cols = [_col("n1", "שעות", "numbers"), _col("f1", "כפול שתיים", "formula", "{n1} * 2")]
    cells = [_cv("n1", "שעות", "numbers", text="21"),
             _cv("f1", "כפול שתיים", "formula", text="", display_value="42")]
    d = _import(client, admin_id, _resp([_item("פריט", cells)], cols)).json()

    col = next(c for c in _cols(d["id"]) if c["title"] == "כפול שתיים")
    assert col["type"] == "text", col
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.board_id == d["id"]).first()
    assert (t.custom_fields or {})[col["id"]] == "42", "the computed value was not imported"


def test_the_expression_comes_with_it_and_is_reported_as_computable(client, admin_id):
    cols = [_col("n1", "שעות", "numbers"), _col("f1", "כפול שתיים", "formula", "{n1} * 2")]
    cells = [_cv("n1", "שעות", "numbers", text="21"),
             _cv("f1", "כפול שתיים", "formula", display_value="42")]
    d = _import(client, admin_id, _resp([_item("פריט", cells)], cols)).json()
    f = d["report"]["formulas"]
    assert [x["title"] for x in f] == ["כפול שתיים"]
    assert f[0]["formula"] == "{שעות} * 2"
    assert f[0]["computable"] is True, "this one would compute here, and that is worth saying"
    col = next(c for c in _cols(d["id"]) if c["title"] == "כפול שתיים")
    assert col["formula"] == "{שעות} * 2", "the expression was not kept on the column"


def test_a_formula_this_app_cannot_compute_says_why(client, admin_id):
    """SWITCH is monday's own and has no counterpart here — so turning this
    column live would show nothing at all, and the report says so rather than
    leaving it to be found."""
    cols = [_col("n1", "ימים", "numbers"),
            _col("f1", "בזמן?", "formula", "SWITCH({n1}, 1, \"כן\", \"לא\")")]
    cells = [_cv("n1", "ימים", "numbers", text="12"),
             _cv("f1", "בזמן?", "formula", display_value="כן")]
    d = _import(client, admin_id, _resp([_item("פריט", cells)], cols)).json()
    f = d["report"]["formulas"]
    assert [x["title"] for x in f] == ["בזמן?"]
    assert f[0]["computable"] is False
    assert f[0]["unsupported"] == ["SWITCH"]

    col = next(c for c in _cols(d["id"]) if c["title"] == "בזמן?")
    assert col["type"] == "text"
    assert col["formula"] == 'SWITCH({ימים}, 1, "כן", "לא")'
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.board_id == d["id"]).first()
    assert (t.custom_fields or {})[col["id"]] == "כן", "the computed value was lost"


def test_a_formula_over_a_column_that_did_not_come_is_reported_as_such(client, admin_id):
    cols = [_col("f1", "פער", "formula", "{gone} - 1")]
    cells = [_cv("f1", "פער", "formula", display_value="7")]
    d = _import(client, admin_id, _resp([_item("פריט", cells)], cols)).json()
    f = d["report"]["formulas"][0]
    assert f["computable"] is False and f["missing"] == ["gone"]


def test_the_mapping_note_says_the_value_came_as_text_either_way(client, admin_id):
    cols = [_col("n1", "שעות", "numbers"),
            _col("f1", "יחושב", "formula", "{n1} * 2"),
            _col("f2", "לא יחושב", "formula", "SWITCH({n1}, 1, 2)")]
    cells = [_cv("n1", "שעות", "numbers", text="5"),
             _cv("f1", "יחושב", "formula", display_value="10"),
             _cv("f2", "לא יחושב", "formula", display_value="5")]
    d = _import(client, admin_id, _resp([_item("פריט", cells)], cols)).json()
    notes = {m["title"]: (m.get("note") or "") for m in d["report"]["mapping"]}
    for title in ("יחושב", "לא יחושב"):
        assert "הערך המחושב יובא כטקסט" in notes[title], notes[title]
    assert "להפוך אותה לעמודת נוסחה" in notes["יחושב"]
    assert "SWITCH" in notes["לא יחושב"], notes["לא יחושב"]


def test_a_file_without_the_column_definitions_still_imports(client, admin_id):
    """The old query did not ask for them. The computed values come across as
    before, and no formula is invented."""
    cells = [_cv("f1", "נוסחה", "formula", display_value="42")]
    d = _import(client, admin_id, _resp([_item("פריט", cells)])).json()
    assert d["report"]["formulas"] == []
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


def _src():
    import pathlib
    return (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
            ).read_text(encoding="utf-8")


def test_the_report_shows_the_formulas_it_brought():
    for marker in ("r.formulas", "הערך המחושב יובא כטקסט", "פונקציה שאינה נתמכת",
                   "עמודה שלא יובאה", "f.computable"):
        assert marker in _src(), f"the report says nothing about {marker}"


def test_an_imported_formula_can_be_read_and_turned_live_from_the_column_menu():
    """An expression stored on a column and shown nowhere is the same as one that
    did not come across."""
    src = _src()
    assert "נוסחה מיובאת" in src
    assert "makeFormulaCol" in src
    assert "הפוך לעמודת נוסחה מחשבת" in src
    # the menu entry appears for a column that is not a formula column but has one
    assert "c.type!=='formula'&&c.formula" in src
    # and switching is reversible: monday's values are not thrown away
    assert "makeFormulaCol(colId){" in src


def test_the_column_menu_harness():
    """Driven harness: tests/frontend/imported_formula_col.mjs."""
    import pathlib
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = pathlib.Path(__file__).resolve().parent / "frontend" / "imported_formula_col.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
