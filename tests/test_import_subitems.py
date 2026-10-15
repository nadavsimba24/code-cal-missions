"""Group — sub-items in a file import (תתי־פריטים בייבוא).

A file can say "this row belongs under that one" in two ways, and both are read:
the indentation a board exported from here writes — where the structure is the
sheet itself — and a column naming the parent item, which is how a CSV or a
hand-made sheet says the same thing.

The indented shape carries more than the parent link: the groups the board was
divided into, and the grey band naming the columns the sub-items have.
"""
import io

from sqlalchemy.orm import Session
import main as cityos_main
from models import Group, Task


def _sheet(rows, bands=(), levels=None, title="לוח"):
    """A workbook shaped the way this app's export writes one: the first cell of
    each row indented two per level, and a sub-item band painted grey."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = title
    grey = PatternFill("solid", fgColor=cityos_main.IMPORT_SUBHEAD_FILL)
    for i, row in enumerate(rows, start=1):
        for j, v in enumerate(row, start=1):
            ws.cell(row=i, column=j, value=v)
        lvl = (levels or {}).get(i - 1, 0)
        if lvl:
            ws.cell(row=i, column=1).alignment = Alignment(indent=lvl * 2)
        if (i - 1) in bands:
            ws.cell(row=i, column=1).fill = grey
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _imp(client, admin_id, raw, filename="board.xlsx"):
    kind = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if filename.endswith(("xlsx", "xlsm")) else "text/csv")
    return client.post(f"/api/boards/import?actor_id={admin_id}",
                       files={"file": (filename, raw, kind)}, data={"actor_id": admin_id})


def _tasks(board_id):
    with Session(cityos_main.engine) as db:
        return db.query(Task).filter(Task.board_id == board_id).order_by(Task.id).all()


def _kids(board_id, title):
    ts = _tasks(board_id)
    parent = next(t for t in ts if t.title == title)
    return [t for t in ts if t.parent_id == parent.id]


# ── the indented shape a board exported from here has ───────────────────────

def test_an_indented_row_becomes_a_sub_item_of_the_row_above_it(client, admin_id):
    raw = _sheet(
        [["פריט", "הערה"],
         ["תיקון מדרכה", "דחוף"],
         ["", "פירוק האריחים"],
         ["", "יציקה"],
         ["החלפת תמרור", ""]],
        bands=(), levels={1: 1, 2: 2, 3: 2, 4: 1})
    r = _imp(client, admin_id, raw)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["items"] == 2 and d["subitems"] == 2
    kids = _kids(d["id"], "תיקון מדרכה")
    assert [k.title for k in kids] == ["פירוק האריחים", "יציקה"]
    assert _kids(d["id"], "החלפת תמרור") == []


def test_the_grey_band_names_the_sub_items_columns_and_is_not_an_item(client, admin_id):
    raw = _sheet(
        [["פריט", "אחראי"],
         ["תיקון מדרכה", "דנה"],
         ["", "פריט", "קבלן"],
         ["", "פירוק האריחים", "כהן בע\"מ"]],
        bands={2}, levels={1: 1, 2: 2, 3: 2})
    d = _imp(client, admin_id, raw).json()
    assert d["items"] == 1 and d["subitems"] == 1, "the band was counted as an item"
    kid = _kids(d["id"], "תיקון מדרכה")[0]
    cols = {c["title"]: c["id"] for c in d and _cols(d["id"])}
    assert "קבלן" in cols, cols
    assert (kid.custom_fields or {}).get(cols["קבלן"]) == 'כהן בע"מ'


def _cols(board_id):
    with Session(cityos_main.engine) as db:
        from models import Board
        b = db.query(Board).filter(Board.id == board_id).first()
        return [c for c in (b.settings or {}).get("columns", []) if c["id"].startswith("col_")]


def test_sub_items_show_the_columns_the_file_gave_them(client, admin_id):
    """And a column only THEY have stays theirs.

    "קבלן" is named in the band and nowhere in the item header, which is how the
    export writes a sub-item-only column (board.sub_only). Created as an
    ordinary board column it stood on every item too, empty forever — the board
    had a different shape from the one the file describes.
    """
    raw = _sheet(
        [["פריט", "אחראי"],
         ["תיקון מדרכה", "דנה"],
         ["", "פריט", "קבלן"],
         ["", "פירוק", "כהן"]],
        bands={2}, levels={1: 1, 2: 2, 3: 2})
    d = _imp(client, admin_id, raw).json()
    with Session(cityos_main.engine) as db:
        from models import Board
        b = db.query(Board).filter(Board.id == d["id"]).first()
        s = b.settings or {}
        sub_cols, sub_only = s.get("sub_cols"), s.get("sub_only")
    titles = {c["id"]: c["title"] for c in _cols(d["id"])}
    assert sub_cols and sub_cols[0] == "item"
    # it is the sub-items' own column, so it rides in sub_only rather than in
    # the shared subset — the board appends it to the sub-item header itself
    assert [titles[c] for c in (sub_only or [])] == ["קבלן"]
    assert [titles[c] for c in sub_cols[1:]] == []
    # and the value is on the sub-item
    kid = _kids(d["id"], "תיקון מדרכה")[0]
    assert (kid.custom_fields or {}).get(sub_only[0]) == "כהן"


def test_a_column_only_the_sub_items_have_is_not_put_on_the_items(client, admin_id):
    """The items keep the columns the items have. A band column with no item
    counterpart is marked sub_only, which is what keeps it off their rows."""
    raw = _sheet(
        [["פריט", "אחראי"],
         ["תיקון מדרכה", "דנה"],
         ["", "פריט", "אחראי", "שלב"],
         ["", "פירוק", "יואב", "הכנה"]],
        bands={2}, levels={1: 1, 2: 2, 3: 2})
    d = _imp(client, admin_id, raw).json()
    with Session(cityos_main.engine) as db:
        from models import Board
        b = db.query(Board).filter(Board.id == d["id"]).first()
        s = b.settings or {}
    titles = {c["id"]: c["title"] for c in s.get("columns", [])}
    # "אחראי" is on both, so it is one shared column; "שלב" is the sub-items' own
    assert [titles[c] for c in (s.get("sub_only") or [])] == ["שלב"]
    assert [titles[c] for c in (s.get("sub_cols") or [])[1:]] == ["אחראי"]


def test_a_column_the_items_and_the_sub_items_share_is_one_column(client, admin_id):
    raw = _sheet(
        [["פריט", "אחראי"],
         ["תיקון מדרכה", "דנה"],
         ["", "פריט", "אחראי"],
         ["", "פירוק", "יואב"]],
        bands={2}, levels={1: 1, 2: 2, 3: 2})
    d = _imp(client, admin_id, raw).json()
    titles = [c["title"] for c in _cols(d["id"])]
    assert titles.count("אחראי") == 1, titles


def test_the_groups_the_file_names_are_the_boards_groups(client, admin_id):
    raw = _sheet(
        [["פריט"],
         ["תשתיות"],
         ["תיקון מדרכה"],
         ["גינון"],
         ["גיזום"]],
        levels={2: 1, 4: 1})
    d = _imp(client, admin_id, raw).json()
    with Session(cityos_main.engine) as db:
        groups = db.query(Group).filter(Group.board_id == d["id"]).order_by(Group.position).all()
        names = [g.name for g in groups]
        tasks = {t.title: t.group_id for t in db.query(Task).filter(Task.board_id == d["id"]).all()}
        assert names == ["תשתיות", "גינון"], names
        assert tasks["תיקון מדרכה"] == groups[0].id
        assert tasks["גיזום"] == groups[1].id
    assert d["items"] == 2 and d["report"]["groups"] == 2


def test_a_flat_sheet_is_still_a_flat_board(client, admin_id):
    """Nothing about the old behaviour moves for a file that says nothing about
    hierarchy — every row is an item, under the three default stages."""
    raw = _sheet([["פריט", "הערה"], ["ראשון", "א"], ["שני", "ב"]])
    d = _imp(client, admin_id, raw).json()
    assert d["items"] == 2 and d["subitems"] == 0
    with Session(cityos_main.engine) as db:
        names = [g.name for g in db.query(Group).filter(Group.board_id == d["id"])
                 .order_by(Group.position).all()]
    assert names == ["בתכנון", "בביצוע", "הושלם"]


def test_a_sub_item_with_no_item_above_it_is_dropped_not_orphaned(client, admin_id):
    raw = _sheet([["פריט"], ["", "יתום"], ["פריט אמיתי"]], levels={1: 2, 2: 1})
    d = _imp(client, admin_id, raw).json()
    assert d["items"] == 1 and d["subitems"] == 0
    assert [t.title for t in _tasks(d["id"])] == ["פריט אמיתי"]


# ── the parent named by a column, which is how a CSV says it ────────────────

def test_a_parent_column_makes_a_row_a_sub_item(client, admin_id):
    csv = ("פריט,הערה,פריט אב\n"
           "תיקון מדרכה,דחוף,\n"
           "פירוק האריחים,,תיקון מדרכה\n"
           "יציקה,,תיקון מדרכה\n").encode("utf-8")
    d = _imp(client, admin_id, csv, "board.csv").json()
    assert d["items"] == 1 and d["subitems"] == 2
    assert {k.title for k in _kids(d["id"], "תיקון מדרכה")} == {"פירוק האריחים", "יציקה"}
    assert d["report"]["hierarchy"] == "parent_column"


def test_the_parent_column_is_structure_not_a_column_of_its_own(client, admin_id):
    csv = "פריט,פריט אב\nאב,\nבן,אב\n".encode("utf-8")
    d = _imp(client, admin_id, csv, "board.csv").json()
    assert [c["title"] for c in _cols(d["id"])] == [], "the parent column became data"


def test_a_parent_named_below_the_row_pointing_at_it_still_resolves(client, admin_id):
    csv = "פריט,parent\nבן,אב\nאב,\n".encode("utf-8")
    d = _imp(client, admin_id, csv, "board.csv").json()
    assert d["items"] == 1 and d["subitems"] == 1
    assert [k.title for k in _kids(d["id"], "אב")] == ["בן"]


def test_a_parent_that_is_not_in_the_file_is_reported_not_guessed(client, admin_id):
    csv = "פריט,פריט אב\nיתום,לא קיים\nאמיתי,\n".encode("utf-8")
    d = _imp(client, admin_id, csv, "board.csv").json()
    assert d["items"] == 2 and d["subitems"] == 0
    assert d["report"]["parents_unmatched"] == ["לא קיים"]
    assert all(t.parent_id is None for t in _tasks(d["id"]))


def test_a_row_naming_itself_as_its_parent_is_refused(client, admin_id):
    csv = "פריט,פריט אב\nלולאה,לולאה\n".encode("utf-8")
    d = _imp(client, admin_id, csv, "board.csv").json()
    assert _tasks(d["id"])[0].parent_id is None


# ── the round trip this feature exists for ──────────────────────────────────

def test_a_board_exported_from_here_comes_back_with_its_sub_items(client, admin_id):
    bid = client.post("/api/boards", json={"name": "לוח מקור", "user_id": admin_id}).json()["id"]
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "תיקון מדרכה",
                                          "user_id": admin_id}).json()["id"]
    client.post("/api/tasks", json={"board_id": bid, "title": "פירוק האריחים",
                                    "parent_id": tid, "user_id": admin_id})
    # the client ships the grid it is showing; this is the shape exportGrid builds
    payload = {"columns": ["פריט", "הערה"],
               "rows": [{"group": True, "level": 0, "cells": ["תשתיות", ""]},
                        {"level": 1, "cells": ["תיקון מדרכה", "דחוף"]},
                        {"subhead": True, "level": 2, "cells": ["", "פריט"]},
                        {"level": 2, "cells": ["", "פירוק האריחים"]}]}
    exported = client.post(f"/api/boards/{bid}/export/xlsx?actor_id={admin_id}", json=payload)
    assert exported.status_code == 200, exported.text

    d = _imp(client, admin_id, exported.content, "לוח מקור_1.xlsx").json()
    assert d["items"] == 1 and d["subitems"] == 1, d
    assert d["report"]["hierarchy"] == "indent"
    assert [k.title for k in _kids(d["id"], "תיקון מדרכה")] == ["פירוק האריחים"]
    with Session(cityos_main.engine) as db:
        names = [g.name for g in db.query(Group).filter(Group.board_id == d["id"]).all()]
    assert names == ["תשתיות"]


def test_a_conversation_can_belong_to_a_sub_item(client, admin_id):
    """The two imports meet: a message whose item is a sub-item still lands on it."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment
    wb = Workbook()
    ws = wb.active
    for i, row in enumerate([["פריט"], ["תיקון מדרכה"], ["", "פירוק האריחים"]], start=1):
        for j, v in enumerate(row, start=1):
            ws.cell(row=i, column=j, value=v)
    ws.cell(row=2, column=1).alignment = Alignment(indent=2)
    ws.cell(row=3, column=1).alignment = Alignment(indent=4)
    ts = wb.create_sheet("שיחות")
    ts.append(cityos_main.TALK_HEADERS)
    ts.append(["", "פירוק האריחים", "עדכון", "דנה", "2026-01-01 09:00:00",
               "האריחים פורקו", 0, "", 1, ""])
    buf = io.BytesIO()
    wb.save(buf)
    d = _imp(client, admin_id, buf.getvalue()).json()
    assert d["subitems"] == 1 and d["messages"] == 1
    with Session(cityos_main.engine) as db:
        from models import Comment
        c = db.query(Comment).join(Task, Task.id == Comment.task_id).filter(
            Task.board_id == d["id"]).first()
        t = db.query(Task).filter(Task.id == c.task_id).first()
        assert t.title == "פירוק האריחים" and t.parent_id is not None


def test_the_sheet_being_wider_than_its_item_header_invents_no_columns(client, admin_id):
    """A board whose sub-items have more columns than its items exports a sheet
    wider than the item header. Those trailing cells belong to the sub-items —
    read as item columns they would stand on the board named "עמודה 3", empty
    for every row, forever."""
    raw = _sheet(
        [["פריט", "אחראי"],
         ["תיקון מדרכה", "דנה"],
         ["", "פריט", "קבלן"],
         ["", "פירוק", "כהן"]],
        bands={2}, levels={1: 1, 2: 2, 3: 2})
    d = _imp(client, admin_id, raw).json()
    titles = sorted(c["title"] for c in _cols(d["id"]))
    assert titles == ["אחראי", "קבלן"], titles
