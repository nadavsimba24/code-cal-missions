"""ייצוא: תתי-פריטים עם העמודות שלהם, והשיחה בגיליון משלה.

Two things the exported file used to lose.

Sub-items have a column structure of their own, and it is not a subset of the
item's — a board can give them columns that exist nowhere else. Laid out under
the item's headers, exactly those values had no heading to sit under and were
dropped. Each run of sub-items now opens with a header naming its own columns.
That part is built by the client, which is where the board's column structure
lives; what is asserted here is that the server writes the band it is sent,
marks it, and folds it into its item.

The conversation was not exported at all, and could not be shipped by the client
either: the browser holds only the threads whose panel somebody opened. So it is
read here, from the board this caller is already a member of, and written as a
second sheet — one row per message, a reply carrying the id of what it answers,
so a thread can be rebuilt from the file.
"""
import io

import pytest

openpyxl = pytest.importorskip("openpyxl")
from openpyxl import load_workbook  # noqa: E402

TALK = "שיחות"


def _wb(client, bid, uid, grid=None):
    r = client.post(f"/api/boards/{bid}/export/xlsx",
                    json={"user_id": uid, **(grid or {"columns": ["פריט"], "rows": []})})
    assert r.status_code == 200, r.text
    return load_workbook(io.BytesIO(r.content))


def _board(client, uid, name="לוח שיחות"):
    bid = client.post("/api/boards", json={"name": name, "user_id": uid}).json()["id"]
    gid = client.get(f"/api/boards/{bid}?user_id={uid}").json()["groups"][0]["id"]
    return bid, gid


def _rows(ws):
    return [[c.value for c in row] for row in ws.iter_rows(min_row=2)]


# ── the sheet exists, always ───────────────────────────────────────────────
def test_the_file_always_carries_a_conversation_sheet(client, admin_id):
    """Even with nothing said yet: a predictable shape is a readable file."""
    bid, _ = _board(client, admin_id, "לוח שקט")
    wb = _wb(client, bid, admin_id)
    assert TALK in wb.sheetnames
    ws = wb[TALK]
    assert [c.value for c in ws[1]] == ["מספר מזהה", "פריט", "סוג", "מאת", "נכתב",
                                        "תוכן", "לייקים", "קבצים", "מזהה הודעה",
                                        "בתגובה להודעה"]
    assert _rows(ws) == []


def test_the_board_sheet_is_still_the_first_one(client, admin_id):
    bid, _ = _board(client, admin_id, "לוח ראשון")
    wb = _wb(client, bid, admin_id)
    assert wb.sheetnames[0] == "לוח ראשון" and wb.sheetnames[1] == TALK
    assert wb[TALK].sheet_view.rightToLeft


# ── what a message becomes ─────────────────────────────────────────────────
def test_a_comment_becomes_a_row(client, admin_id):
    bid, gid = _board(client, admin_id)
    t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "גשר הרצל", "user_id": admin_id}).json()
    client.post(f"/api/tasks/{t['id']}/comments",
                json={"content": "התחלנו במדידות", "user_id": admin_id})

    row = _rows(_wb(client, bid, admin_id)[TALK])[0]
    assert row[0] == t["item_uid"]        # the number the board shows for the item
    assert row[1] == "גשר הרצל"
    assert row[2] == "עדכון"
    assert row[3]                          # written by somebody
    assert row[5] == "התחלנו במדידות"
    assert row[6] == 0                     # likes, counted not listed


def test_a_reply_is_its_own_row_and_points_at_what_it_answers(client, admin_id):
    bid, gid = _board(client, admin_id)
    t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "מדרכות", "user_id": admin_id}).json()
    c = client.post(f"/api/tasks/{t['id']}/comments",
                    json={"content": "שאלה", "user_id": admin_id}).json()
    client.post(f"/api/tasks/{t['id']}/comments",
                json={"content": "תשובה", "parent_id": c["id"], "user_id": admin_id})

    rows = _rows(_wb(client, bid, admin_id)[TALK])
    kinds = {r[5]: (r[2], r[8], r[9]) for r in rows}
    assert kinds["שאלה"][0] == "עדכון" and kinds["שאלה"][2] in (None, "")
    kind, mid, parent = kinds["תשובה"]
    assert kind == "תגובה"
    assert parent == kinds["שאלה"][1]      # the thread is rebuildable from the file
    assert mid != parent


def test_a_subitems_conversation_is_on_the_board_too(client, admin_id):
    """A sub-item is an item here: its thread would otherwise be the one part
    of the board's conversation the file quietly lost."""
    bid, gid = _board(client, admin_id)
    p = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "אב", "user_id": admin_id}).json()
    s = client.post("/api/tasks", json={"board_id": bid, "parent_id": p["id"],
                                        "title": "תת", "user_id": admin_id}).json()
    client.post(f"/api/tasks/{s['id']}/comments",
                json={"content": "הערה על תת-הפריט", "user_id": admin_id})

    rows = _rows(_wb(client, bid, admin_id)[TALK])
    assert [r[1] for r in rows] == ["תת"]
    assert rows[0][5] == "הערה על תת-הפריט"


def test_messages_come_in_the_order_they_were_written(client, admin_id):
    bid, gid = _board(client, admin_id)
    t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "סדר", "user_id": admin_id}).json()
    for n in ("ראשון", "שני", "שלישי"):
        client.post(f"/api/tasks/{t['id']}/comments", json={"content": n, "user_id": admin_id})
    assert [r[5] for r in _rows(_wb(client, bid, admin_id)[TALK])] == ["ראשון", "שני", "שלישי"]


def test_the_timestamp_is_a_real_date_excel_can_sort(client, admin_id):
    import datetime as dt
    bid, gid = _board(client, admin_id)
    t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "זמן", "user_id": admin_id}).json()
    client.post(f"/api/tasks/{t['id']}/comments", json={"content": "מתי", "user_id": admin_id})
    cell = _wb(client, bid, admin_id)[TALK].cell(row=2, column=5)
    assert isinstance(cell.value, dt.datetime)
    assert cell.number_format == "DD/MM/YYYY HH:MM"


def test_another_boards_conversation_is_not_in_this_file(client, admin_id):
    a_id, a_gid = _board(client, admin_id, "לוח א")
    b_id, b_gid = _board(client, admin_id, "לוח ב")
    for bid, gid, text in ((a_id, a_gid, "של א"), (b_id, b_gid, "של ב")):
        t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                            "title": "פריט", "user_id": admin_id}).json()
        client.post(f"/api/tasks/{t['id']}/comments", json={"content": text, "user_id": admin_id})
    assert [r[5] for r in _rows(_wb(client, a_id, admin_id)[TALK])] == ["של א"]


def test_a_comment_starting_with_equals_is_still_never_a_formula(client, admin_id):
    """The injection guard covers the new sheet too — a comment is user text."""
    bid, gid = _board(client, admin_id)
    t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "נוסחה", "user_id": admin_id}).json()
    client.post(f"/api/tasks/{t['id']}/comments",
                json={"content": "=HYPERLINK(\"http://x\")", "user_id": admin_id})
    cell = _wb(client, bid, admin_id)[TALK].cell(row=2, column=6)
    assert cell.value == "=HYPERLINK(\"http://x\")" and cell.data_type == "s"


def test_a_non_member_gets_no_file_and_so_no_conversation(client, admin_id, guinea_id):
    bid, gid = _board(client, admin_id, "לוח סגור")
    t = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "פריט", "user_id": admin_id}).json()
    client.post(f"/api/tasks/{t['id']}/comments", json={"content": "סודי", "user_id": admin_id})
    r = client.post(f"/api/boards/{bid}/export/xlsx",
                    json={"user_id": guinea_id, "columns": ["פריט"], "rows": []})
    assert r.status_code == 403


# ── the sub-item band on the board sheet ───────────────────────────────────
def _band_grid():
    """What the client sends for one item with two sub-items of its own shape."""
    return {"columns": ["פריט", "סטטוס", "", ""], "rows": [
        {"group": True, "level": 0, "cells": ["בביצוע", "", "", ""]},
        {"level": 1, "cells": ["גשר הרצל", "בתהליך", "", ""]},
        {"subhead": True, "level": 2, "cells": ["", "שם", "אחראי", "שעות"]},
        {"level": 2, "cells": ["", "מדידות", "דנה", 12]},
        {"level": 2, "cells": ["", "מכרז", "רון", 40]},
    ]}


def test_the_subitem_band_names_its_own_columns(client, admin_id):
    ws = _wb(client, 1, admin_id, _band_grid()).worksheets[0]
    assert [c.value for c in ws[4]] == [None, "שם", "אחראי", "שעות"]
    assert [c.value for c in ws[5]] == [None, "מדידות", "דנה", 12]


def test_the_band_is_marked_as_a_header_not_left_as_a_row(client, admin_id):
    ws = _wb(client, 1, admin_id, _band_grid()).worksheets[0]
    filled = ws.cell(row=4, column=2)
    assert filled.fill.fgColor.rgb == "FFEDEFF5"
    plain = ws.cell(row=5, column=2)                  # a sub-item row is not filled
    assert plain.fill.fgColor.rgb != "FFEDEFF5"


def test_the_band_folds_into_its_item_with_the_sub_items(client, admin_id):
    """The header belongs to the block, so it collapses with it."""
    ws = _wb(client, 1, admin_id, _band_grid()).worksheets[0]
    assert ws.row_dimensions[3].outlineLevel == 1     # the item, folding into its group
    assert [ws.row_dimensions[r].outlineLevel for r in (4, 5, 6)] == [2, 2, 2]


def test_a_sheet_is_as_wide_as_the_wider_of_the_two_structures(client, admin_id):
    """Sub-item columns can outnumber the item's; the header simply runs out of
    names, and the values still land."""
    ws = _wb(client, 1, admin_id, _band_grid()).worksheets[0]
    assert ws.max_column == 4
    assert [c.value for c in ws[1]] == ["פריט", "סטטוס", None, None]
