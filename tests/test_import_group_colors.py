"""Group — an imported board keeps the colours its groups had.

A group's header colour is how a board is read before a word of it is: the red
one is the one on fire, the green one is done. The import was creating groups
in a palette of this app's own, cycled by position, so a board migrated off
monday arrived recoloured — "דחוף" green, "הושלם" red — and every one of those
colours looked like a decision somebody here had made.

Three files can say what colour a group is, and all three are read:

  * a monday API response, in `groups { … color }` — monday answers a hex
    string, and older responses answer the colour's name;
  * monday's own Excel export, which fills the group's row with it;
  * this app's own export, which writes it on the group row's text — so a board
    exported from here and imported back comes home the colour it left.

A file that says nothing about colour still gets the palette. That is a default,
and it is reported as one; what it must never do is pass for the source board.
"""
import io
import json

import pytest
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy.orm import Session

import import_monday
import main as cityos_main
from models import Group

H = {"X-CityOS-User": "1", "host": "localhost"}


# ── files ──────────────────────────────────────────────────────────────────
def _monday_json(groups, items=None):
    """A monday response whose board states its groups — `groups` is
    [(id, title, colour as monday answers it), …]."""
    board = {
        "name": "לוח מאנדיי",
        "groups": [{"id": gid, "title": title, **({"color": color} if color is not None else {})}
                   for gid, title, color in groups],
        "items_page": {"cursor": None, "items": items if items is not None else [
            {"id": "1", "name": "פריט", "group": {"id": groups[0][0], "title": groups[0][1]},
             "column_values": [{"id": "t", "type": "text", "column": {"title": "הערה"},
                                "text": "ערך"}]},
        ]},
    }
    return json.dumps({"data": {"boards": [board]}}, ensure_ascii=False).encode()


def _painted_sheet(groups, header=("Name", "Subitems", "מטפל"), board="לוח מאנדיי", on_text=False):
    """monday's Excel layout, each group's row painted — `groups` is
    [(title, colour or None), …]. `on_text` writes the colour the way this app's
    own export does: on the font rather than as a fill."""
    wb = Workbook()
    ws = wb.active
    ws.append([board])
    for title, color in groups:
        ws.append([title])
        if color:
            cell = ws.cell(row=ws.max_row, column=1)
            argb = "FF" + color[1:].upper()
            if on_text:
                cell.font = Font(color=argb)
            else:
                cell.fill = PatternFill("solid", fgColor=argb)
        ws.append(list(header))
        ws.append([f"פריט ב{title}", "", "רינה"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _imp(client, raw, filename="board.xlsx"):
    r = client.post("/api/boards/import",
                    files={"file": (filename, raw, "application/octet-stream")},
                    data={}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def _colors(board_id):
    with Session(cityos_main.engine) as db:
        return [(g.name, g.color) for g in db.query(Group)
                .filter(Group.board_id == board_id).order_by(Group.position)]


# ── reading monday's colour ────────────────────────────────────────────────
@pytest.mark.parametrize("raw, want", [
    ("#037F4C", "#037f4c"),            # what monday answers, in the case it answers it
    ("#e2445c", "#e2445c"),
    ("#fc0", "#ffcc00"),               # the three-digit shorthand
    ("stuck-red", "#e2445c"),          # the colour by name, as older responses give it
    ("working_orange", "#fdab3d"),
    ("Dark Blue", "#0086c0"),          # spelled with a space, and capitalised
    ("", None),                        # a field that came back empty
    (None, None),
    ("chartreuse", None),              # a name this table does not hold
    ("#12345", None),                  # not a colour at all
    ("rgb(1,2,3)", None),
])
def test_a_monday_colour_is_read_or_left_alone(raw, want):
    """Left alone, not guessed at: a wrong colour is worse than a default one,
    because a default looks like a default."""
    assert import_monday.group_color(raw) == want


# ── a monday API response ──────────────────────────────────────────────────
def test_the_groups_arrive_in_the_colours_monday_gave_them(client):
    d = _imp(client, _monday_json([("g1", "דחוף", "#e2445c"),
                                   ("g2", "בעבודה", "#fdab3d"),
                                   ("g3", "הושלם", "#00c875")]),
             filename="response.json")
    assert _colors(d["id"]) == [("דחוף", "#e2445c"), ("בעבודה", "#fdab3d"), ("הושלם", "#00c875")]
    assert d["report"]["group_colors"] == 3
    assert d["report"]["group_hex"] == ["#e2445c", "#fdab3d", "#00c875"]


def test_a_colour_monday_names_instead_of_spelling_is_read_too(client):
    d = _imp(client, _monday_json([("g1", "דחוף", "stuck-red")]), filename="response.json")
    assert _colors(d["id"]) == [("דחוף", "#e2445c")]


def test_a_file_without_colours_gets_the_palette_and_says_so(client):
    """The groups still arrive, in this app's own colours — and the report says
    they are this app's, so nobody reads them as the board's."""
    d = _imp(client, _monday_json([("g1", "דחוף", None), ("g2", "הושלם", None)]),
             filename="response.json")
    got = _colors(d["id"])
    assert [n for n, _ in got] == ["דחוף", "הושלם"]
    assert [c for _, c in got] == cityos_main.IMPORT_PALETTE[:2]
    assert d["report"]["group_colors"] == 0
    assert d["report"]["groups"] == 2


def test_one_group_without_a_colour_does_not_cost_the_others_theirs(client):
    d = _imp(client, _monday_json([("g1", "דחוף", "#e2445c"),
                                   ("g2", "ללא", None),
                                   ("g3", "הושלם", "#00c875")]),
             filename="response.json")
    got = dict(_colors(d["id"]))
    assert got["דחוף"] == "#e2445c" and got["הושלם"] == "#00c875"
    assert got["ללא"] == cityos_main.IMPORT_PALETTE[1]
    assert d["report"]["group_colors"] == 2


# ── monday's Excel export ──────────────────────────────────────────────────
def test_a_painted_group_row_is_the_groups_colour(client):
    d = _imp(client, _painted_sheet([("משימות", "#784bd1"), ("באגים", "#e2445c")]))
    assert _colors(d["id"]) == [("משימות", "#784bd1"), ("באגים", "#e2445c")]
    assert d["report"]["group_colors"] == 2


def test_the_colour_this_apps_own_export_writes_on_the_text_is_read_back(client):
    """A board exported from here and imported back comes home the colour it
    left — the export writes each group's own colour on its row."""
    d = _imp(client, _painted_sheet([("משימות", "#0086c0"), ("באגים", "#ff642e")], on_text=True))
    assert _colors(d["id"]) == [("משימות", "#0086c0"), ("באגים", "#ff642e")]


def test_an_unpainted_sheet_still_divides_the_board(client):
    """Colour is the one thing missing, and the groups themselves are not."""
    d = _imp(client, _painted_sheet([("משימות", None), ("באגים", None)]))
    got = _colors(d["id"])
    assert [n for n, _ in got] == ["משימות", "באגים"]
    assert [c for _, c in got] == cityos_main.IMPORT_PALETTE[:2]
    assert d["report"]["group_colors"] == 0


def test_black_text_on_a_plain_sheet_is_not_read_as_a_colour(client):
    """Every cell in an ordinary spreadsheet is black on white. Read as a
    choice, every group in every plain file would arrive black."""
    d = _imp(client, _painted_sheet([("משימות", "#000000"), ("באגים", "#FFFFFF")]))
    assert [c for _, c in _colors(d["id"])] == cityos_main.IMPORT_PALETTE[:2]


# ── out and back ───────────────────────────────────────────────────────────
def test_a_board_exported_from_here_and_imported_back_keeps_its_colours(client, admin_id):
    """The whole round trip through the real endpoints: the export writes each
    group's own colour on its row, and the import reads it back as that group's.
    Before this the export wrote the BOARD's colour on every group row, so every
    group came home the same shade whatever it had been."""
    grid = {"columns": ["פריט", "סטטוס"], "rows": [
        {"group": True, "gcolor": "#784bd1", "level": 0, "cells": ["דחוף", ""]},
        {"level": 1, "cells": ["פריט א", "בתהליך"]},
        {"group": True, "gcolor": "#00c875", "level": 0, "cells": ["הושלם", ""]},
        {"level": 1, "cells": ["פריט ב", "הושלם"]},
    ]}
    r = client.post("/api/boards/1/export/xlsx", json={"user_id": admin_id, **grid})
    assert r.status_code == 200, r.text
    back = _imp(client, r.content, filename="חזרה.xlsx")
    assert _colors(back["id"]) == [("דחוף", "#784bd1"), ("הושלם", "#00c875")]


def test_a_group_row_with_no_colour_of_its_own_still_exports(client, admin_id):
    """It falls back to the board's colour, which is how the sheet read before
    groups carried one — an older client sends no `gcolor` at all."""
    grid = {"columns": ["פריט", "סטטוס"], "rows": [
        {"group": True, "level": 0, "cells": ["קבוצה", ""]},
        {"level": 1, "cells": ["פריט", "בתהליך"]},
    ]}
    r = client.post("/api/boards/1/export/xlsx", json={"user_id": admin_id, **grid})
    assert r.status_code == 200, r.text
