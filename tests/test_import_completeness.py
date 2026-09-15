"""Group — does an import say whether everything came in?

A migration's failure mode is not crashing, it is arriving short and looking
complete. Two things are asserted here: that a column with data in it is not
dropped merely for being the 41st, and that the report compares what came in
against what the file held, so "did I lose items?" is answerable at a glance.
"""
import json
import pathlib
import re

import main as cityos_main

SRC = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html").read_text(encoding="utf-8")


def _monday(items, columns):
    """A response whose items carry every one of `columns`."""
    return json.dumps({"data": {"boards": [{"id": "1", "name": "לוח רחב", "items_page": {
        "items": [{"id": str(i), "name": n,
                   "column_values": [{"id": f"c{j}", "type": "text",
                                      "column": {"title": c}, "text": f"{n}-{j}"}
                                     for j, c in enumerate(columns)]}
                  for i, n in enumerate(items, start=1)]}}]}}).encode()


def _import(client, admin_id, raw):
    return client.post(f"/api/boards/import?actor_id={admin_id}",
                       files={"file": ("board.json", raw, "application/json")},
                       data={"actor_id": admin_id})


def test_a_real_monday_board_does_not_lose_columns_to_the_ceiling(client, admin_id):
    """64 columns is what a municipal board actually carries; the ceiling used to
    be 40 and five columns with data in them fell off it."""
    cols = [f"עמודה {i}" for i in range(64)]
    d = _import(client, admin_id, _monday(["פריט א", "פריט ב"], cols)).json()
    r = d["report"]
    assert r["columns_found"] == 64
    assert r["columns_imported"] >= 64, r["columns_imported"]
    assert not [s for s in r["skipped"] if "תקרה" in s["reason"]], r["skipped"]


def test_the_ceiling_still_exists_and_says_what_it_cut(client, admin_id):
    cols = [f"עמודה {i}" for i in range(cityos_main.IMPORT_MAX_COLS + 10)]
    d = _import(client, admin_id, _monday(["פריט"], cols)).json()
    r = d["report"]
    over = [s for s in r["skipped"] if "תקרה" in s["reason"]]
    assert over, "a board past the ceiling lost columns and said nothing"
    assert r["columns_imported"] == cityos_main.IMPORT_MAX_COLS - 1
    assert all(s["title"] for s in over), "a dropped column has to be named"


def test_the_report_carries_what_the_file_held_next_to_what_came_in(client, admin_id):
    d = _import(client, admin_id, _monday(["א", "ב", "ג"], ["עמודה"])).json()
    assert d["items"] == 3 and d["report"]["items"] == 3
    assert d["report"]["updates"] == 0


def test_the_tiles_are_read_against_the_file_not_on_their_own():
    """A bare "320 פריטים" beside a "39/64 עמודות" is what makes a complete
    import look like a lossy one."""
    assert "const outOf=(got,inFile,label)" in SRC
    for tile in ("'פריטים'", "'פריטי־תת'", "'הודעות בשיחות'"):
        assert re.search(r"outOf\([^)]*" + re.escape(tile), SRC), f"{tile} is not compared to the file"


def _monday_cols(colspecs, items=2):
    """A response whose columns are (title, type, filled?) triples."""
    return json.dumps({"data": {"boards": [{"id": "1", "name": "לוח", "items_page": {
        "items": [{"id": str(i), "name": f"פריט {i}",
                   "column_values": [{"id": f"c{j}", "type": ctype,
                                      "column": {"title": title},
                                      "text": (f"ערך {i}" if filled else "")}
                                     for j, (title, ctype, filled) in enumerate(colspecs)]}
                  for i in range(1, items + 1)]}}]}}).encode()


def test_a_column_with_no_value_on_any_item_is_not_created(client, admin_id):
    """monday's response carries a cell for every column the board holds,
    including the ones nobody sees — one hidden in the board's view, an archived
    one, a formula whose result the query never asked for. Created here they are
    columns that are not on the board she migrated, standing empty in front of
    the board that is."""
    d = _import(client, admin_id, _monday_cols([("מלאה", "text", True),
                                                ("ריקה", "text", False)])).json()
    r = d["report"]
    assert r["columns_imported"] == 1
    assert r["columns_empty"] == ["ריקה"]
    titles = [c["title"] for c in _cols(d["id"])]
    assert titles == ["מלאה"], titles


def test_a_column_that_was_not_created_is_still_named(client, admin_id):
    """Not created is not the same as not mentioned: the report says which
    columns the file held and had nothing in, so "where is it?" is answerable
    without counting columns against monday."""
    r = _import(client, admin_id, _monday_cols([("מלאה", "text", True),
                                                ("ריקה", "text", False)])).json()["report"]
    assert r["columns_empty"] == ["ריקה"]
    assert not [s for s in r["skipped"] if s["title"] == "ריקה"], \
        "an empty column is not a column that was lost"


def test_an_empty_column_never_reaches_the_ceiling_at_all(client, admin_id):
    """It carries none of the board, so it does not get to cost a column that
    does — it is gone before the ceiling is counted."""
    specs = [(f"מלאה {i}", "text", True) for i in range(cityos_main.IMPORT_MAX_COLS)]
    specs.append(("ריקה", "text", False))
    r = _import(client, admin_id, _monday_cols(specs)).json()["report"]
    over = [s["title"] for s in r["skipped"] if "תקרה" in s["reason"]]
    assert "ריקה" not in over, over
    assert r["columns_imported"] == cityos_main.IMPORT_MAX_COLS - 1
    assert r["columns_empty"] == ["ריקה"]


def test_the_sub_items_column_is_not_reported_as_a_column_that_was_lost(client, admin_id):
    """Its content is the sub-items. Listed among "did not import", it says the
    opposite of what happened — which is exactly how it was read."""
    doc = {"data": {"boards": [{"id": "1", "name": "לוח", "items_page": {"items": [
        {"id": "1", "name": "פריט", "column_values": [
            {"id": "c1", "type": "subtasks", "column": {"title": "תתי משימות"}, "text": ""},
            {"id": "c2", "type": "text", "column": {"title": "הערה"}, "text": "ערך"}],
         "subitems": [{"id": "s1", "name": "תת־פריט", "column_values": []}]}]}}]}}
    d = _import(client, admin_id, json.dumps(doc).encode()).json()
    r = d["report"]
    assert d["subitems"] == 1
    assert r["as_subitems"] == ["תתי משימות"]
    assert not [s for s in r["skipped"] if s["title"] == "תתי משימות"]
    assert "תתי משימות" not in [c["title"] for c in _cols(d["id"])], \
        "the sub-items column became a column of its own"


def _cols(board_id):
    from sqlalchemy.orm import Session
    from models import Board
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        return [c for c in (b.settings or {}).get("columns", []) if c["id"].startswith("col_")]


def test_the_report_says_where_the_sub_items_and_the_empty_columns_went():
    for marker in ("as_subitems", "columns_empty", "עמודות ריקות שלא נוצרו",
                   "אינה עמודה כאן"):
        assert marker in SRC, f"the report says nothing about {marker}"


def test_a_column_the_file_never_asked_for_is_not_called_empty(client, admin_id):
    """A formula column whose file was exported without display_value is a file
    to re-export. Filed under "empty in every item", it looks like a column
    nobody uses — and the board quietly loses six of them."""
    doc = {"data": {"boards": [{"id": "1", "name": "לוח", "items_page": {"items": [
        {"id": "1", "name": "פריט", "column_values": [
            {"id": "c1", "type": "formula", "column": {"title": "ימים עד לעליה"},
             "text": "", "value": None},                      # no display_value asked for
            {"id": "c2", "type": "text", "column": {"title": "ריקה באמת"}, "text": ""}]}]}}]}}
    r = _import(client, admin_id, json.dumps(doc).encode()).json()["report"]
    assert r["columns_need_reexport"] == [{"title": "ימים עד לעליה", "type": "formula"}]
    assert r["columns_empty"] == ["ריקה באמת"]


def test_a_formula_the_file_DID_ask_for_and_that_is_genuinely_empty(client, admin_id):
    """asked for, and still empty — that one really is an empty column."""
    doc = {"data": {"boards": [{"id": "1", "name": "לוח", "items_page": {"items": [
        {"id": "1", "name": "פריט", "column_values": [
            {"id": "c1", "type": "formula", "column": {"title": "נוסחה"},
             "text": "", "value": None, "display_value": ""}]}]}}]}}
    r = _import(client, admin_id, json.dumps(doc).encode()).json()["report"]
    assert r["columns_need_reexport"] == []
    assert r["columns_empty"] == ["נוסחה"]


def test_the_report_tells_the_two_apart():
    assert "columns_need_reexport" in SRC
    for marker in ("יש להן ערכים במאנדיי", "הן לא ריקות במאנדיי",
                   "שום דבר לא נמחק", "מה עושים", "monday_export.graphql",
                   # they are not created, and the notice has to say that rather
                   # than "imported" — which is what it used to say
                   "עמודות שלא נוצרו", "ייווצרו עם הערכים"):
        assert marker in SRC, f"the fixable-columns notice does not say {marker}"
    for marker in ("הן ריקות גם במאנדיי", "ייצוא מחדש לא ישנה כאן דבר",
                   "להבדיל מהעמודות שלמעלה", "מוסתרות/בארכיון"):
        assert marker in SRC, f"the genuinely-empty notice does not say {marker}"


def test_the_notice_explains_each_kind_of_column_in_its_own_terms():
    """"a formula is computed, not stored" and "the linked item names" are two
    different explanations; one list of names gives neither."""
    assert "REEXP_HE" in SRC
    for kind in ("formula:", "board_relation:", "mirror:"):
        assert kind in SRC.split("REEXP_HE")[1][:600], kind
