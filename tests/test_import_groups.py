"""Group — does an imported board arrive divided the way its source was?

A board is not a list. Its division into groups is most of how the people who
built it read it, and three of the four files this app imports state that
division in a place that was not being read:

  * monday's own Excel export writes the board's name on a line of its own, then
    for every group that group's name on a line of its own followed by a fresh
    copy of the header. Read as one table from row 0 — which is what happened —
    the board's NAME became the header row, so every column arrived titled
    "עמודה 3", the header and the group names arrived as items, and all 241 items
    landed in one invented group.
  * a flat sheet can only name each row's group in a column.
  * a monday API response carries the division only if the query asked for it,
    and an export that did not is not a board with one group — it is a question
    the file was never asked.

Measured against her real files before the fix: Spotical → 241 items, 0 groups,
0 column titles; after → 231 items in Tasks/Bugs/New Group with every column
named. ניהול תוכן אתר החברה → 670 flat items; after → 37 items, 615 sub-items,
4 groups.
"""
import io
import json
import pathlib

import pytest
from openpyxl import Workbook
from sqlalchemy.orm import Session

import main as cityos_main
from models import Board, Group, Task

SRC = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html").read_text(encoding="utf-8")


# ── files in the shapes the app has to read ────────────────────────────────
def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _monday_sheet(groups, header=("Name", "Subitems", "מטפל", "סטטוס"), board="לוח מאנדיי",
                  summary=False):
    """monday's own export: the board's name, then a title + header per group.

    `groups` is [(group title, [(item name, subitems column, cells…), …]), …];
    an item whose row is followed by sub-items carries them as
    ("__subs__", [(name, cells…), …]).
    """
    rows = [[board]]
    for title, items in groups:
        rows.append([title])
        rows.append(list(header))
        for it in items:
            if it[0] == "__subs__":
                rows.append([header[1], header[0]] + list(header[2:]))   # the band
                for sub in it[1]:
                    rows.append([""] + list(sub))
            else:
                rows.append(list(it))
        if summary:
            rows.append(["", "", "", "2024-05-05 to 2024-05-30"])       # the group's roll-up
    return _xlsx(rows)


def _imp(client, admin_id, raw, filename="board.xlsx"):
    r = client.post(f"/api/boards/import?actor_id={admin_id}",
                    files={"file": (filename, raw, "application/octet-stream")},
                    data={"actor_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()


def _groups(board_id):
    with Session(cityos_main.engine) as db:
        out = []
        for g in db.query(Group).filter(Group.board_id == board_id).order_by(Group.position):
            n = db.query(Task).filter(Task.group_id == g.id, Task.parent_id.is_(None)).count()
            out.append((g.name, n))
        return out


def _titles(board_id):
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        return [c["title"] for c in (b.settings or {}).get("columns", [])
                if c["id"].startswith("col_")]


# ── monday's own Excel export ──────────────────────────────────────────────
def test_a_monday_export_arrives_divided_the_way_the_board_was(client, admin_id):
    raw = _monday_sheet([
        ("משימות", [("פריט א", "", "רינה", "בעבודה"), ("פריט ב", "", "דנה", "הסתיים")]),
        ("באגים", [("פריט ג", "", "רינה", "בעבודה")]),
    ])
    d = _imp(client, admin_id, raw)
    assert _groups(d["id"]) == [("משימות", 2), ("באגים", 1)]
    assert d["report"]["groups"] == 2
    assert d["report"]["groups_from"] == "sheet"
    assert d["report"]["group_names"] == ["משימות", "באגים"]


def test_the_group_titles_and_the_repeated_headers_are_not_items(client, admin_id):
    """They were: the board came in with "משימות" and "Name" as its first two
    items, which is what a group divider looks like when nobody reads it."""
    d = _imp(client, admin_id, _monday_sheet([
        ("משימות", [("פריט א", "", "רינה", "בעבודה")]),
        ("באגים", [("פריט ב", "", "דנה", "הסתיים")]),
    ]))
    with Session(cityos_main.engine) as db:
        names = [t.title for t in db.query(Task).filter(Task.board_id == d["id"])]
    assert sorted(names) == ["פריט א", "פריט ב"], names
    assert d["items"] == 2


def test_the_columns_keep_their_names_instead_of_becoming_column_3(client, admin_id):
    """The board's name was being read as the header row, so every column in
    every monday Excel import was titled "עמודה N" and the board arrived
    unreadable."""
    d = _imp(client, admin_id, _monday_sheet([("משימות", [("פריט", "", "רינה", "בעבודה")])]))
    assert _titles(d["id"]) == ["מטפל", "סטטוס"]
    assert not any(t.startswith("עמודה ") for t in _titles(d["id"]))


def test_the_board_is_called_what_it_calls_itself(client, admin_id):
    """The first line of the file is the board's name; the file it was saved as
    is whatever the browser called it — "Spotical_1786443119"."""
    d = _imp(client, admin_id,
             _monday_sheet([("משימות", [("פריט", "", "רינה", "בעבודה")])], board="ניהול תוכן"),
             filename="ניהול תוכן_1786016922 (1).xlsx")
    assert d["name"] == "ניהול תוכן"


def test_a_name_given_by_hand_still_wins_over_the_file(client, admin_id):
    raw = _monday_sheet([("משימות", [("פריט", "", "רינה", "בעבודה")])], board="שם בקובץ")
    r = client.post(f"/api/boards/import?actor_id={admin_id}",
                    files={"file": ("b.xlsx", raw, "application/octet-stream")},
                    data={"actor_id": admin_id, "name": "שם שנבחר"})
    assert r.status_code == 200 and r.json()["name"] == "שם שנבחר"


def test_the_sub_items_under_mondays_band_come_in_as_sub_items(client, admin_id):
    """monday has no indentation to read: it writes a header of its own over the
    sub-item block, its column's title first and the item column's second."""
    d = _imp(client, admin_id, _monday_sheet([
        ("משימות", [("דף הבית", "א, ב", "רינה", "בעבודה"),
                    ("__subs__", [("א", "רינה", "הסתיים"), ("ב", "דנה", "בעבודה")]),
                    ("דף שני", "", "דנה", "בעבודה")]),
    ]))
    assert (d["items"], d["subitems"]) == (2, 2)
    assert d["report"]["hierarchy"] == "band"
    with Session(cityos_main.engine) as db:
        parent = db.query(Task).filter(Task.board_id == d["id"], Task.title == "דף הבית").first()
        subs = db.query(Task).filter(Task.parent_id == parent.id).all()
        assert sorted(s.title for s in subs) == ["א", "ב"]
        # and under the parent's group, not somewhere of their own
        assert {s.group_id for s in subs} == {parent.group_id}


def test_mondays_subitems_column_is_not_kept_beside_the_sub_items_it_names(client, admin_id):
    """It holds the same names again, comma-joined, as text."""
    d = _imp(client, admin_id, _monday_sheet([
        ("משימות", [("דף הבית", "א, ב", "רינה", "בעבודה"),
                    ("__subs__", [("א", "רינה", "הסתיים")])]),
    ]))
    assert "Subitems" not in _titles(d["id"]), _titles(d["id"])
    assert d["report"]["as_subitems"] == ["Subitems"]


def test_the_line_monday_writes_under_each_group_is_not_an_item(client, admin_id):
    """It has no name and one rolled-up date. Imported, it is a "פריט 38" that
    belongs to nobody — four of the forty-one items her real file "had"."""
    d = _imp(client, admin_id, _monday_sheet([
        ("משימות", [("פריט א", "", "רינה", "בעבודה")]),
        ("באגים", [("פריט ב", "", "דנה", "הסתיים")]),
    ], summary=True))
    assert d["items"] == 2
    assert d["report"]["summary_rows"] == 2
    assert _groups(d["id"]) == [("משימות", 1), ("באגים", 1)]


def test_an_item_with_a_name_and_nothing_else_is_still_an_item(client, admin_id):
    """A lone cell is a group title only where the header follows it; anywhere
    else it is an item nobody has filled in yet, and dropping it loses a row."""
    d = _imp(client, admin_id, _monday_sheet([
        ("משימות", [("פריט א", "", "רינה", "בעבודה"), ("פריט ריק",), ("פריט ג", "", "", "")]),
    ]))
    with Session(cityos_main.engine) as db:
        names = sorted(t.title for t in db.query(Task).filter(Task.board_id == d["id"]))
    assert names == ["פריט א", "פריט ג", "פריט ריק"], names
    assert _groups(d["id"]) == [("משימות", 3)]


# ── a flat sheet that names the group in a column ──────────────────────────
@pytest.mark.parametrize("head", ["קבוצה", "Group", "group name"])
def test_a_column_naming_the_group_divides_the_board(client, admin_id, head):
    csv = f"פריט,{head},אחראי\nבור בכביש,תשתיות,רינה\nגן,תחזוקה,דנה\nפנס,תשתיות,רינה\n"
    d = _imp(client, admin_id, csv.encode(), "board.csv")
    assert _groups(d["id"]) == [("תשתיות", 2), ("תחזוקה", 1)]
    assert d["report"]["groups_from"] == "column"
    assert d["report"]["groups_column"] == head


def test_the_group_column_is_not_also_kept_as_a_column(client, admin_id):
    d = _imp(client, admin_id, "פריט,קבוצה,אחראי\nא,תשתיות,רינה\n".encode(), "b.csv")
    assert _titles(d["id"]) == ["אחראי"]


def test_a_row_naming_no_group_is_not_filed_under_the_first_one(client, admin_id):
    """Filing it under whatever group happens to come first is a misplacement
    nobody would find; a group of its own says what is true of it."""
    csv = "פריט,קבוצה\nא,תשתיות\nב,\nג,תשתיות\n"
    d = _imp(client, admin_id, csv.encode(), "b.csv")
    assert _groups(d["id"]) == [("תשתיות", 2), ("ללא קבוצה", 1)]


def test_group_rows_beat_a_group_column_when_a_file_has_both(client, admin_id):
    """The rows are the board's own structure; the column is one of its fields."""
    raw = _monday_sheet([("משימות", [("פריט א", "", "רינה", "אחר")])],
                        header=("Name", "Subitems", "מטפל", "קבוצה"))
    d = _imp(client, admin_id, raw)
    assert _groups(d["id"]) == [("משימות", 1)]
    assert d["report"]["groups_from"] == "sheet"


# ── a file with no division at all ─────────────────────────────────────────
def test_a_flat_file_still_gets_the_three_stages_and_says_so(client, admin_id):
    d = _imp(client, admin_id, "פריט,אחראי\nא,רינה\nב,דנה\n".encode(), "b.csv")
    assert [g for g, _ in _groups(d["id"])] == ["בתכנון", "בביצוע", "הושלם"]
    assert d["report"]["groups"] == 0, "three groups nobody asked for are not a division"
    assert d["report"]["groups_from"] == "default"


def test_a_board_exported_from_here_comes_home_divided(client, admin_id):
    """The indented shape this app writes was already read; it has to stay read
    — the monday layout is recognised beside it, never instead of it."""
    from openpyxl import Workbook as _W
    wb = _W()
    ws = wb.active
    ws.append(["נושאים", "אחראי"])
    for lvl, row in [(0, ["בתכנון", ""]), (1, ["פריט א", "רינה"]),
                     (0, ["בביצוע", ""]), (1, ["פריט ב", "דנה"]), (1, ["פריט ג", ""])]:
        ws.append(row)
        ws.cell(row=ws.max_row, column=1).alignment = \
            ws.cell(row=ws.max_row, column=1).alignment.copy(indent=lvl * 2)
    buf = io.BytesIO()
    wb.save(buf)
    d = _imp(client, admin_id, buf.getvalue())
    assert _groups(d["id"]) == [("בתכנון", 1), ("בביצוע", 2)]
    assert d["report"]["groups_from"] == "sheet"
    assert _titles(d["id"]) == ["אחראי"]


# ── the monday API response ────────────────────────────────────────────────
def _json_board(groups=True):
    items = [{"id": "1", "name": "פריט א", "column_values": []},
             {"id": "2", "name": "פריט ב", "column_values": []}]
    board = {"id": "1", "name": "לוח", "items_page": {"items": items}}
    if groups:
        board["groups"] = [{"id": "g1", "title": "תשתיות"}, {"id": "g2", "title": "חינוך"}]
        items[0]["group"] = {"id": "g1", "title": "תשתיות"}
        items[1]["group"] = {"id": "g2", "title": "חינוך"}
    return json.dumps({"data": {"boards": [board]}}).encode()


def test_a_response_that_carries_the_groups_is_divided_by_them(client, admin_id):
    d = _imp(client, admin_id, _json_board(), "board.json")
    assert _groups(d["id"]) == [("תשתיות", 1), ("חינוך", 1)]
    assert d["report"]["groups_need_reexport"] is False
    assert d["report"]["groups_from"] == "file"
    assert d["report"]["group_names"] == ["תשתיות", "חינוך"]


def test_a_response_that_was_never_asked_for_the_groups_says_so(client, admin_id):
    """Her own 320-item export: no `groups`, no `group` on any item, every item
    in one unnamed group. Reported as "1 group" that is indistinguishable from a
    board that really has one."""
    d = _imp(client, admin_id, _json_board(groups=False), "board.json")
    assert d["report"]["groups_need_reexport"] is True
    assert d["report"]["groups"] == 0
    assert [g for g, _ in _groups(d["id"])] == [""], "a name here is a heading over nothing"


def test_groups_in_the_file_but_no_group_on_the_items_is_said_out_loud(client, admin_id):
    """The half-answered export: the board's `groups` came, `group` on the items
    did not. Every item lands in the first group — "פתוח" over all of them —
    while the report reads "2 קבוצות, החלוקה נקראה מהקובץ". The count is the
    only thing that separates that from a division actually imported."""
    raw = _json_board()
    doc = json.loads(raw)
    for it in doc["data"]["boards"][0]["items_page"]["items"]:
        it.pop("group")
    d = _imp(client, admin_id, json.dumps(doc).encode(), "board.json")
    rep = d["report"]
    assert rep["groups"] == 2 and rep["groups_need_reexport"] is False
    assert rep["items_ungrouped"] == 2, "both items arrived with no group of their own"
    assert rep["ungrouped_into"] == "תשתיות", "the group they all ended up in, by name"
    assert _groups(d["id"]) == [("תשתיות", 2), ("חינוך", 0)]


def test_a_division_that_did_come_across_reports_nothing_ungrouped(client, admin_id):
    rep = _imp(client, admin_id, _json_board(), "board.json")["report"]
    assert rep["items_ungrouped"] == 0 and rep["ungrouped_into"] == ""


def test_the_report_says_when_the_items_came_without_their_group():
    for marker in ("items_ungrouped", "ungrouped_into",
                   "אף פריט לא הגיע עם שיוך לקבוצה", "פריטים הגיעו בלי שיוך לקבוצה"):
        assert marker in SRC, f"the import report says nothing about {marker}"


# ── the board's own name ───────────────────────────────────────────────────
def test_a_board_whose_export_carries_its_name_arrives_under_it(client, admin_id):
    d = _imp(client, admin_id, _json_board(), "response1992g.json")
    assert d["name"] == "לוח"
    assert d["report"]["board_name_from"] == "file"


def test_a_board_named_after_the_download_says_so(client, admin_id):
    """Her own export: no `name` on the board, so the only name left was what the
    browser called the file. The board is right to arrive under it — and the one
    thing the report must not do is let it pass for the board's name."""
    doc = json.loads(_json_board())
    doc["data"]["boards"][0].pop("name")
    d = _imp(client, admin_id, json.dumps(doc).encode(), "response1992g.json")
    assert d["name"] == "response1992g"
    assert d["report"]["board_name_from"] == "filename"
    assert d["report"]["board_name"] == "response1992g"


def test_a_name_typed_at_import_wins_over_both(client, admin_id):
    r = client.post(f"/api/boards/import?actor_id={admin_id}",
                    files={"file": ("response1992g.json", _json_board(), "application/json")},
                    data={"actor_id": admin_id, "name": "פיתוח לוחות"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "פיתוח לוחות" and d["report"]["board_name_from"] == "typed"


def test_a_pretty_printed_export_is_not_rejected_for_its_indentation(client, admin_id):
    """Her re-export was 11.7MB and refused; the content was 3.66MB and the rest
    was the indentation Postman adds when a response is saved from its pretty
    view. A board must not be turned away over how its file was formatted."""
    doc = json.loads(_json_board())
    pretty = json.dumps(doc, ensure_ascii=False, indent=4).encode()
    compact = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(pretty) > len(compact)
    for raw in (pretty, compact):
        d = _imp(client, admin_id, raw, "board.json")
        assert d["name"] == "לוח" and d["report"]["groups"] == 2


def test_a_file_past_the_ceiling_is_told_its_size_and_the_reason(client, admin_id):
    big = b'{"data":{"boards":[{"name":"x","items_page":{"items":[]}}]}}' + b" " * (
        cityos_main.IMPORT_MAX_UPLOAD_MB * 1024 * 1024)
    r = client.post(f"/api/boards/import?actor_id={admin_id}",
                    files={"file": ("board.json", big, "application/json")},
                    data={"actor_id": admin_id})
    assert r.status_code == 413
    detail = r.json()["detail"]
    assert str(cityos_main.IMPORT_MAX_UPLOAD_MB) in detail, "the ceiling is named"
    assert "MB" in detail and "פוסטמן" in detail, "and the usual reason, which is actionable"


def test_the_report_says_where_the_name_came_from():
    for marker in ("board_name_from", "על שם הקובץ, לא על שם הלוח", "שם הלוח נקרא מהקובץ"):
        assert marker in SRC, f"the import report says nothing about {marker}"


def test_the_query_shipped_with_the_app_asks_for_the_division():
    q = (pathlib.Path(__file__).resolve().parent.parent
         / "backend" / "monday_export.graphql").read_text(encoding="utf-8")
    assert q.count("groups { id title }") >= 1
    assert q.count("group { id title }") >= 2, "the second page has to ask for it too"


# ── what the report says ───────────────────────────────────────────────────
def test_the_report_states_the_division_and_where_it_came_from():
    for marker in ("groups_need_reexport", "group_names", "groups_from", "summary_rows",
                   "fa-layer-group", "הקובץ אינו אומר איך הלוח מחולק",
                   "אינו מחלק את הלוח לקבוצות", "שורות הקבוצה שבין הפריטים",
                   "עמודת הקבוצה שבקובץ"):
        assert marker in SRC, f"the import report says nothing about {marker}"


def test_the_report_reads_the_three_cases_differently():
    """Driven harness: tests/frontend/import_groups.mjs."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = pathlib.Path(__file__).resolve().parent / "frontend" / "import_groups.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_a_sheet_past_the_import_ceiling_says_what_it_cut(client, admin_id):
    """The tabular import cut at 2,000 rows without a word — and a board short by
    its tail reads exactly like a board that is that size."""
    over = cityos_main.IMPORT_MAX_ROWS + 25
    csv = "פריט,אחראי\n" + "".join(f"פריט {i},רינה\n" for i in range(over))
    d = _imp(client, admin_id, csv.encode(), "b.csv")
    assert d["report"]["rows_dropped"] == 25
    assert d["items"] == cityos_main.IMPORT_MAX_ROWS


def test_a_sheet_inside_the_ceiling_reports_nothing_cut(client, admin_id):
    d = _imp(client, admin_id, "פריט,אחראי\nא,רינה\n".encode(), "b.csv")
    assert d["report"]["rows_dropped"] == 0


def test_a_nameless_row_that_carries_a_name_in_its_second_cell_is_kept(client, admin_id):
    """That is the shape of a sub-item whose band went unread. Counted as one of
    monday's summary lines, it would be a row of the board dropped in silence —
    so only a row with no name anywhere is treated as the group's roll-up."""
    raw = _xlsx([["לוח"], ["משימות"], ["Name", "Subitems", "מטפל", "סטטוס"],
                 ["פריט א", "", "רינה", "בעבודה"],
                 ["", "שורה עם שם בתא השני", "דנה", "הסתיים"],
                 ["", "", "", "2024-05-05 to 2024-05-30"]])
    d = _imp(client, admin_id, raw)
    assert d["report"]["summary_rows"] == 1
    with Session(cityos_main.engine) as db:
        n = db.query(Task).filter(Task.board_id == d["id"]).count()
    assert n == 2, "the row with a name in it was dropped"


# ── the order the file reads in ─────────────────────────────────────────────
# The three columns the system issues — מספר מזהה / מועד יצירה / יוצר הרשומה —
# used to be written in FRONT of everything the file held, so a migrated board
# read three columns of metadata before it read anything anybody wrote.

def _all_titles(board_id):
    from models import Board
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        return [c["title"] for c in (b.settings or {}).get("columns", [])]


def test_the_columns_come_in_the_order_the_file_reads(client, admin_id):
    raw = _monday_sheet([("קבוצה", [("פריט", "", "רינה", "בעבודה")])],
                        header=("Name", "Subitems", "מטפל", "סטטוס"))
    d = _imp(client, admin_id, raw)
    assert _all_titles(d["id"]) == ["מטפל", "סטטוס", "מספר מזהה", "מועד יצירה", "יוצר הרשומה"]


def test_a_csv_keeps_its_own_order_too(client, admin_id):
    csv = "פריט,ג,א,ב\nx,1,2,3\n"
    d = _imp(client, admin_id, csv.encode(), "b.csv")
    assert _all_titles(d["id"])[:3] == ["ג", "א", "ב"], "the sheet's order was rearranged"


def test_the_system_columns_are_still_there_and_still_work(client, admin_id):
    """Moved, not dropped: they are what shows an item's identifier and who
    created it, on an imported board like on any other."""
    d = _imp(client, admin_id, "פריט,הערה\nא,משהו\n".encode(), "b.csv")
    from models import Board
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == d["id"]).first()
        ids = [c["id"] for c in (b.settings or {})["columns"]]
    assert ids[-3:] == ["sys_item_id", "sys_created_at", "sys_created_by"]
    got = client.get(f"/api/boards/{d['id']}?user_id={admin_id}").json()
    item = got["tasks"][0] if got.get("tasks") else got["groups"][0]["tasks"][0]
    assert item.get("item_uid"), "the identifier column has nothing to show"


def test_a_monday_response_keeps_the_boards_order_with_the_system_columns_last(client, admin_id):
    doc = {"data": {"boards": [{"id": "1", "name": "לוח",
        "columns": [{"id": "c2", "title": "שנייה", "type": "text"},
                    {"id": "c1", "title": "ראשונה", "type": "text"}],
        "items_page": {"items": [{"id": "1", "name": "פריט", "column_values": [
            {"id": "c1", "type": "text", "column": {"title": "ראשונה"}, "text": "א"},
            {"id": "c2", "type": "text", "column": {"title": "שנייה"}, "text": "ב"}]}]}}]}}
    d = _imp(client, admin_id, json.dumps(doc).encode(), "b.json")
    assert _all_titles(d["id"]) == ["שנייה", "ראשונה", "מספר מזהה", "מועד יצירה", "יוצר הרשומה"]


# ── a formula the spreadsheet never worked out ─────────────────────────────
def _xlsx_with_formula(uncalculated=True):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["פריט", "מספר", "מחושב"])
    ws.append(["א", 21, "=B2*2"])
    ws.append(["ב", 7, "=B3*2"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_a_formula_cell_with_no_value_in_the_file_comes_across_as_the_formula(client, admin_id):
    """openpyxl reads values, and a formula Excel never calculated has none. The
    column arrived empty on every item — a column nobody filled, said of a
    column the file is explicit about."""
    d = _imp(client, admin_id, _xlsx_with_formula())
    assert d["report"]["formula_cells_as_text"] == 2
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == d["id"]).first()
        col = next(c for c in (b.settings or {})["columns"] if c.get("title") == "מחושב")
        assert col["type"] == "text", col
        vals = sorted((t.custom_fields or {}).get(col["id"], "")
                      for t in db.query(Task).filter(Task.board_id == d["id"]))
    assert vals == ["=B2*2", "=B3*2"], vals


def test_a_file_with_the_values_in_it_is_not_read_twice(client, admin_id):
    """The second read is only worth its cost where there are formulas, and a
    file that has none is answered from its own XML without one."""
    d = _imp(client, admin_id, _xlsx([["פריט", "מספר"], ["א", 5]]))
    assert d["report"]["formula_cells_as_text"] == 0


def test_a_csv_is_not_searched_for_formulas(client, admin_id):
    d = _imp(client, admin_id, "פריט,מחושב\nא,=B2*2\n".encode(), "b.csv")
    assert d["report"]["formula_cells_as_text"] == 0
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.board_id == d["id"]).first()
        assert "=B2*2" in (t.custom_fields or {}).values(), "a CSV's text is its text"


def test_the_report_explains_the_uncalculated_cells():
    for marker in ("formula_cells_as_text", "תאים עם נוסחה שלא חושבה בקובץ",
                   "הנוסחה עצמה יובאה כטקסט", "לפתוח את הקובץ באקסל"):
        assert marker in SRC, f"the report says nothing about {marker}"
