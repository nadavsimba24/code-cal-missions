"""Status — an imported board keeps the colours its statuses had.

A status is read as a colour before it is read as a word: the red one is stuck,
the green one is done. The import was giving every status column's vocabulary
colours out of this app's own palette, cycled by position — so a board migrated
in arrived with "הושלם" red and "תקוע" green, and every one of those colours
looked like a decision somebody here had made.

The same three files that say what colour a group is say what colour a status
is, and all three are read:

  * a monday API response, where the vocabulary lives in the column's own
    settings — `labels` beside `labels_colors` — and, for a query that asked
    only for the items, in each cell's own `label_style`;
  * monday's Excel export, which fills every status cell with that label's
    colour;
  * this app's own export, which fills it the same way — so a board exported
    from here and imported back comes home with the statuses it left with, as
    a status column rather than as a column of grey words.

A file that paints nothing still gets the palette. That is a default, and it is
reported as one; what it must never do is pass for the source board.
"""
import io
import json

import pytest
from openpyxl import Workbook
from openpyxl.styles import PatternFill

import import_monday
import main as cityos_main

H = {"X-CityOS-User": "1", "host": "localhost"}


# ── files ──────────────────────────────────────────────────────────────────
def _cv(cid, title, ctype, text="", **extra):
    return {"id": cid, "type": ctype, "column": {"title": title}, "text": text, **extra}


def _resp(items, columns=None, board_name="לוח מאנדיי"):
    """A monday response. `columns` is the board-level column definitions —
    where a status column's vocabulary properly lives."""
    b = {"name": board_name, "items_page": {"cursor": None, "items": items}}
    if columns is not None:
        b["columns"] = columns
    return json.dumps({"data": {"boards": [b]}}, ensure_ascii=False).encode()


def _status_col_def(cid, title, labels, colors):
    """monday's own definition of a status column: the two maps, keyed by the
    label's index, inside settings_str — which monday answers as a JSON
    *string*, not as a nested object."""
    return {"id": cid, "title": title, "type": "status",
            "settings_str": json.dumps({"labels": labels, "labels_colors": colors},
                                       ensure_ascii=False)}


def _items(cid, title, values):
    return [{"id": str(i + 1), "name": f"פריט {i + 1}",
             "column_values": [_cv(cid, title, "status", text=v)]}
            for i, v in enumerate(values)]


def _painted_sheet(header, rows, board="לוח מאנדיי", group="קבוצה"):
    """monday's Excel layout, with each cell painted where the row says so —
    `rows` is [[(value, colour or None), …], …]."""
    wb = Workbook()
    ws = wb.active
    ws.append([board])
    ws.append([group])
    ws.append(list(header))
    for row in rows:
        ws.append([v for v, _ in row])
        for col, (_, color) in enumerate(row, start=1):
            if color:
                ws.cell(row=ws.max_row, column=col).fill = PatternFill(
                    "solid", fgColor="FF" + color[1:].upper())
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _imp(client, raw, filename="board.xlsx"):
    r = client.post("/api/boards/import",
                    files={"file": (filename, raw, "application/octet-stream")},
                    data={}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def _col(client, board_id, title):
    board = client.get(f"/api/boards/{board_id}?user_id=1", headers=H).json()
    return next(c for c in board["columns"] if c.get("title") == title)


def _vocab(client, board_id, title):
    """[(label, colour), …] — the words the column offers, in its own order."""
    return [(o["label"], o["color"]) for o in (_col(client, board_id, title)["options"] or [])]


def _cells(client, board_id, cid):
    board = client.get(f"/api/boards/{board_id}?user_id=1", headers=H).json()
    return [(t["title"], (t.get("custom_fields") or {}).get(cid)) for t in board["tasks"]]


# ── reading monday's definition ────────────────────────────────────────────
def test_the_two_maps_are_joined_on_the_index_they_share():
    got = import_monday.status_colors({
        "labels": {"0": "בעבודה", "1": "הושלם", "5": "תקוע"},
        "labels_colors": {"0": {"color": "#fdab3d", "border": "#E99729"},
                          "1": {"color": "#00c875", "border": "#00B461"},
                          "5": {"color": "#e2445c", "border": "#CE3048"}}})
    assert got == {"בעבודה": "#fdab3d", "הושלם": "#00c875", "תקוע": "#e2445c"}


def test_a_colour_monday_states_only_by_name_is_read_too():
    """`var_name` is the same palette by the other spelling — the half an older
    response carries instead of the hex."""
    got = import_monday.status_colors({
        "labels": {"0": "הושלם"},
        "labels_colors": {"0": {"var_name": "done-green"}}})
    assert got == {"הושלם": "#00c875"}


def test_the_newer_shape_states_each_word_with_its_own_colour():
    got = import_monday.status_colors(
        {"labels": [{"id": 1, "name": "בעבודה", "color": "#fdab3d"},
                    {"id": 2, "name": "הושלם", "color": "#00c875"}]})
    assert got == {"בעבודה": "#fdab3d", "הושלם": "#00c875"}


@pytest.mark.parametrize("settings", [
    None, {}, "not a dict", {"labels": {"0": "הושלם"}},             # colours not stated
    {"labels": {"0": "הושלם"}, "labels_colors": {"0": {"color": "chartreuse"}}},
    {"labels": {"0": "הושלם"}, "labels_colors": {"1": {"color": "#00c875"}}},  # a different word
])
def test_a_word_the_file_gives_no_colour_for_is_left_out(settings):
    """Left out, not guessed at — the importer then gives it a colour of its
    own, which looks like a default instead of a claim about the source board."""
    assert import_monday.status_colors(settings) == {}


def test_a_cell_states_the_colour_of_its_own_label():
    assert import_monday.cell_label_color(
        {"label_style": {"color": "#e2445c", "border": "#CE3048"}}) == "#e2445c"
    assert import_monday.cell_label_color(
        {"label_style": json.dumps({"color": "#00c875"})}) == "#00c875"
    assert import_monday.cell_label_color({"text": "הושלם"}) is None


# ── a monday API response ──────────────────────────────────────────────────
def test_the_vocabulary_arrives_in_the_colours_monday_gave_it(client):
    cols = [_status_col_def("s", "שלב", {"0": "בעבודה", "1": "הושלם", "2": "תקוע"},
                            {"0": {"color": "#fdab3d"}, "1": {"color": "#00c875"},
                             "2": {"color": "#e2445c"}})]
    d = _imp(client, _resp(_items("s", "שלב", ["בעבודה", "הושלם", "תקוע", "הושלם"]), cols),
             filename="response.json")
    assert _vocab(client, d["id"], "שלב") == [("בעבודה", "#fdab3d"), ("הושלם", "#00c875"),
                                              ("תקוע", "#e2445c")]
    assert d["report"]["status_colors"] == 3
    assert d["report"]["status_options"] == 3
    assert d["report"]["status_cols"] == 1


def test_a_cells_own_colour_stands_in_when_the_file_has_no_definitions(client):
    """A query that asked for the items and not for the board's columns carries
    no vocabulary at all — but each cell still says what colour its own word
    is, and that is the same colour."""
    items = [{"id": "1", "name": "פריט", "column_values": [
                 _cv("s", "שלב", "status", text="תקוע",
                     label_style={"color": "#e2445c", "border": "#CE3048"})]},
             {"id": "2", "name": "פריט ב", "column_values": [
                 _cv("s", "שלב", "status", text="הושלם",
                     label_style={"color": "#00c875", "border": "#00B461"})]}]
    d = _imp(client, _resp(items), filename="response.json")
    assert _vocab(client, d["id"], "שלב") == [("תקוע", "#e2445c"), ("הושלם", "#00c875")]
    assert d["report"]["status_colors"] == 2


def test_the_columns_own_definition_wins_over_a_cell(client):
    """A cell's colour is a copy; the column's vocabulary is the original. A
    board recoloured after that cell was last rendered is the board's own."""
    cols = [_status_col_def("s", "שלב", {"0": "הושלם"}, {"0": {"color": "#037f4c"}})]
    items = [{"id": "1", "name": "פריט", "column_values": [
        _cv("s", "שלב", "status", text="הושלם", label_style={"color": "#00c875"})]}]
    d = _imp(client, _resp(items, cols), filename="response.json")
    assert _vocab(client, d["id"], "שלב") == [("הושלם", "#037f4c")]


def test_a_file_without_status_colours_gets_the_palette_and_says_so(client):
    """The words still arrive, in this app's own colours — and the report says
    they are this app's, so nobody reads them as the board's."""
    d = _imp(client, _resp(_items("s", "שלב", ["בעבודה", "הושלם"])), filename="response.json")
    got = _vocab(client, d["id"], "שלב")
    assert [lbl for lbl, _ in got] == ["בעבודה", "הושלם"]
    assert [c for _, c in got] == cityos_main.IMPORT_PALETTE[:2]
    assert d["report"]["status_colors"] == 0
    assert d["report"]["status_options"] == 2


def test_one_word_without_a_colour_does_not_cost_the_others_theirs(client):
    cols = [_status_col_def("s", "שלב", {"0": "בעבודה", "1": "ללא", "2": "הושלם"},
                            {"0": {"color": "#fdab3d"}, "2": {"color": "#00c875"}})]
    d = _imp(client, _resp(_items("s", "שלב", ["בעבודה", "ללא", "הושלם"]), cols),
             filename="response.json")
    got = dict(_vocab(client, d["id"], "שלב"))
    assert got["בעבודה"] == "#fdab3d" and got["הושלם"] == "#00c875"
    assert got["ללא"] == cityos_main.IMPORT_PALETTE[1]
    assert d["report"]["status_colors"] == 2


def test_the_cells_point_at_the_option_in_the_colour_it_arrived_with(client):
    cols = [_status_col_def("s", "שלב", {"0": "תקוע"}, {"0": {"color": "#e2445c"}})]
    d = _imp(client, _resp(_items("s", "שלב", ["תקוע"]), cols), filename="response.json")
    col = _col(client, d["id"], "שלב")
    (_, cell), = _cells(client, d["id"], col["id"])
    assert cell["label"] == "תקוע" and cell["color"] == "#e2445c"
    assert cell["id"] == col["options"][0]["id"], \
        "the cell does not point at the option the column offers"


# ── monday's Excel export ──────────────────────────────────────────────────
def test_a_painted_column_arrives_as_a_status_column_in_those_colours(client):
    d = _imp(client, _painted_sheet(
        ["Name", "מטפל", "סטטוס"],
        [[("דף הבית", None), ("רינה", None), ("הושלם", "#00c875")],
         [("טפסים", None), ("דנה", None), ("תקוע", "#e2445c")],
         [("מפה", None), ("רינה", None), ("הושלם", "#00c875")]]))
    assert _vocab(client, d["id"], "סטטוס") == [("הושלם", "#00c875"), ("תקוע", "#e2445c")]
    assert d["report"]["status_cols"] == 1
    assert d["report"]["status_colors"] == 2


def test_the_words_beside_it_stay_the_text_they_are(client):
    """Only the painted column is a status column. A name column that repeats
    is a name column, and a board whose "מטפל" became a status is a board that
    cannot be assigned to anybody."""
    d = _imp(client, _painted_sheet(
        ["Name", "מטפל", "סטטוס"],
        [[("דף הבית", None), ("רינה", None), ("הושלם", "#00c875")],
         [("טפסים", None), ("רינה", None), ("תקוע", "#e2445c")]]))
    assert _col(client, d["id"], "מטפל")["type"] == "text"


def test_an_unpainted_column_of_repeated_words_is_not_a_status_column(client):
    """Repetition is not the signal — plenty of text columns repeat. The paint
    is, and a sheet that paints nothing is not describing a vocabulary."""
    d = _imp(client, _painted_sheet(
        ["Name", "מטפל", "סטטוס"],
        [[("דף הבית", None), ("רינה", None), ("הושלם", None)],
         [("טפסים", None), ("דנה", None), ("תקוע", None)],
         [("מפה", None), ("רינה", None), ("הושלם", None)]]))
    col = _col(client, d["id"], "סטטוס")
    assert col["type"] == "text" and not col["options"]
    assert d["report"]["status_cols"] == 0


def test_a_single_stray_fill_does_not_make_a_column_a_vocabulary(client):
    """Somebody highlighted one cell. That is a highlight, not a status column
    — and read as one, the other four words arrive as options nobody chose."""
    rows = [[(f"פריט {i}", None), ("רינה", None),
             (f"הערה חופשית {i}", "#ffcb00" if i == 0 else None)] for i in range(5)]
    d = _imp(client, _painted_sheet(["Name", "מטפל", "הערות"], rows))
    assert _col(client, d["id"], "הערות")["type"] == "text"


def test_a_column_of_sentences_is_prose_somebody_highlighted(client):
    long = "פסקה ארוכה שמישהו צבע כדי שתבלוט, והיא בבירור לא סטטוס של פריט"
    d = _imp(client, _painted_sheet(
        ["Name", "מטפל", "תיאור"],
        [[("א", None), ("רינה", None), (long, "#ffcb00")],
         [("ב", None), ("דנה", None), (long + " שוב", "#ffcb00")]]))
    assert _col(client, d["id"], "תיאור")["type"] == "text"


# ── out and back ───────────────────────────────────────────────────────────
def test_a_board_exported_from_here_and_imported_back_keeps_its_statuses(client, admin_id):
    """The whole round trip through the real endpoints: the export fills each
    status cell with that option's colour, and the import reads the fill back
    as the column's vocabulary. Before this the column came home as free text —
    every cell a grey word, and a picker with nothing in it."""
    grid = {"columns": ["פריט", "סטטוס"], "rows": [
        {"group": True, "gcolor": "#784bd1", "level": 0, "cells": ["דחוף", ""]},
        {"level": 1, "cells": ["פריט א", {"v": "בתהליך", "c": "#fdab3d"}]},
        {"level": 1, "cells": ["פריט ב", {"v": "הושלם", "c": "#00c875"}]},
        {"level": 1, "cells": ["פריט ג", {"v": "בתהליך", "c": "#fdab3d"}]},
    ]}
    r = client.post("/api/boards/1/export/xlsx", json={"user_id": admin_id, **grid})
    assert r.status_code == 200, r.text
    back = _imp(client, r.content, filename="חזרה.xlsx")
    assert _vocab(client, back["id"], "סטטוס") == [("בתהליך", "#fdab3d"), ("הושלם", "#00c875")]
    cid = _col(client, back["id"], "סטטוס")["id"]
    assert [(t, c["label"]) for t, c in _cells(client, back["id"], cid)] == [
        ("פריט א", "בתהליך"), ("פריט ב", "הושלם"), ("פריט ג", "בתהליך")]


def test_the_word_for_an_unset_cell_does_not_become_one_of_the_options(client, admin_id):
    """"טרם הוגדר" is the absence of a status, and the export writes it for a
    cell nobody set. Read back as a word the column offers, it would stand in
    the picker of a board that never had it — and every unset cell would come
    home holding a value."""
    grid = {"columns": ["פריט", "סטטוס"], "rows": [
        {"group": True, "gcolor": "#784bd1", "level": 0, "cells": ["קבוצה", ""]},
        {"level": 1, "cells": ["פריט א", {"v": "הושלם", "c": "#00c875"}]},
        {"level": 1, "cells": ["פריט ב", {"v": "טרם הוגדר", "c": "#c4c4c4"}]},
    ]}
    r = client.post("/api/boards/1/export/xlsx", json={"user_id": admin_id, **grid})
    assert r.status_code == 200, r.text
    back = _imp(client, r.content, filename="חזרה.xlsx")
    assert _vocab(client, back["id"], "סטטוס") == [("הושלם", "#00c875")]
    cid = _col(client, back["id"], "סטטוס")["id"]
    assert dict(_cells(client, back["id"], cid))["פריט ב"] is None, \
        "an unset cell came home holding a status"


def test_the_groups_colours_still_come_home_beside_the_statuses(client, admin_id):
    """The group rows are painted too, and reading the body's fills must not
    cost them that — they are read off the same sheet."""
    grid = {"columns": ["פריט", "סטטוס"], "rows": [
        {"group": True, "gcolor": "#784bd1", "level": 0, "cells": ["דחוף", ""]},
        {"level": 1, "cells": ["פריט א", {"v": "בתהליך", "c": "#fdab3d"}]},
        {"group": True, "gcolor": "#00c875", "level": 0, "cells": ["הושלם", ""]},
        {"level": 1, "cells": ["פריט ב", {"v": "הושלם", "c": "#00c875"}]},
    ]}
    r = client.post("/api/boards/1/export/xlsx", json={"user_id": admin_id, **grid})
    assert r.status_code == 200, r.text
    back = _imp(client, r.content, filename="חזרה.xlsx")
    board = client.get(f"/api/boards/{back['id']}?user_id=1", headers=H).json()
    assert [(g["name"], g["color"]) for g in board["groups"]] == [("דחוף", "#784bd1"),
                                                                 ("הושלם", "#00c875")]
    assert back["report"]["group_colors"] == 2 and back["report"]["status_colors"] == 2


# ── the report ─────────────────────────────────────────────────────────────
def test_the_report_says_whose_colours_the_statuses_are():
    """Driven harness: tests/frontend/import_status_colors.mjs — the three
    cases (all from the file, some, none) have to read differently, or a board
    wearing this app's palette passes for the board it was migrated from."""
    import pathlib
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = pathlib.Path(__file__).resolve().parent / "frontend" / "import_status_colors.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
