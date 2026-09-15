"""Group — the imported board keeps the source board's column order.

The ceiling decides WHICH columns survive; it has no business deciding their
order. Sorted by how full each column happens to be, a 60-column board comes
back rearranged — the same columns, in an order nobody chose, and every view,
export and screenshot of it then differs from the board it was migrated from.
"""
import json

from sqlalchemy.orm import Session
import main as cityos_main
import import_monday
from models import Board


def _cv(cid, title, ctype="text", text="ערך"):
    return {"id": cid, "type": ctype, "column": {"title": title}, "text": text}


def _resp(items, columns=None, name="לוח"):
    board = {"id": "1", "name": name, "items_page": {"items": items}}
    if columns is not None:
        board["columns"] = columns
    return json.dumps({"data": {"boards": [board]}}).encode()


def _import(client, admin_id, raw):
    r = client.post(f"/api/boards/import?actor_id={admin_id}",
                    files={"file": ("board.json", raw, "application/json")},
                    data={"actor_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()


def _titles(board_id):
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        return [c["title"] for c in (b.settings or {}).get("columns", [])
                if str(c["id"]).startswith("col_")]


def test_the_columns_come_out_in_the_order_the_file_has_them(client, admin_id):
    """They used to come out fullest-first, which is a different board."""
    cells = [_cv("c1", "ראשונה", text="ערך"),
             _cv("c2", "שנייה", text=""),          # emptier — used to jump to the end
             _cv("c3", "שלישית", text="ערך"),
             _cv("c4", "רביעית", text="")]
    d = _import(client, admin_id, _resp([{"id": "1", "name": "פריט",
                                          "column_values": cells}]))
    assert _titles(d["id"]) == ["ראשונה", "שנייה", "שלישית", "רביעית"], _titles(d["id"])


def test_a_partly_filled_board_is_not_reordered_by_how_full_it_is(client, admin_id):
    """Two items, and the middle column is the only full one."""
    def item(i, middle):
        return {"id": str(i), "name": f"פריט {i}",
                "column_values": [_cv("a", "א", text="" if i == 1 else "ערך"),
                                  _cv("b", "ב", text=middle),
                                  _cv("c", "ג", text="")]}
    d = _import(client, admin_id, _resp([item(1, "מלא"), item(2, "מלא")]))
    assert _titles(d["id"]) == ["א", "ב", "ג"], _titles(d["id"])


def test_the_boards_own_column_list_decides_the_order(client, admin_id):
    """When the export carries `columns`, that is the order the board shows —
    it beats the order the cells happen to arrive in."""
    cols = [{"id": "c3", "title": "שלישית", "type": "text"},
            {"id": "c1", "title": "ראשונה", "type": "text"},
            {"id": "c2", "title": "שנייה", "type": "text"}]
    cells = [_cv("c1", "ראשונה"), _cv("c2", "שנייה"), _cv("c3", "שלישית")]
    d = _import(client, admin_id, _resp([{"id": "1", "name": "פריט",
                                          "column_values": cells}], cols))
    assert _titles(d["id"]) == ["שלישית", "ראשונה", "שנייה"], _titles(d["id"])


def test_the_ceiling_still_keeps_the_fullest_columns(client, admin_id):
    """The order is the board's; which columns survive is still decided by what
    actually carries the board."""
    n = cityos_main.IMPORT_MAX_COLS + 5
    cells = [_cv(f"c{i}", f"עמודה {i}", text=("" if i == 0 else "ערך")) for i in range(n)]
    d = _import(client, admin_id, _resp([{"id": "1", "name": "פריט",
                                          "column_values": cells}]))
    r = d["report"]
    over = [s["title"] for s in r["skipped"] if "תקרה" in s["reason"]]
    assert "עמודה 0" in over, "the empty column survived ahead of full ones"
    kept = _titles(d["id"])
    # and what survived is still in the file's order, not sorted by fill
    nums = [int(t.split()[-1]) for t in kept]
    assert nums == sorted(nums), kept


def test_a_tabular_import_keeps_the_sheet_order(client, admin_id):
    csv = "פריט,ג,א,ב\nשורה,1,2,3\n".encode("utf-8")
    r = client.post(f"/api/boards/import?actor_id={admin_id}",
                    files={"file": ("board.csv", csv, "text/csv")},
                    data={"actor_id": admin_id})
    assert r.status_code == 200, r.text
    assert _titles(r.json()["id"]) == ["ג", "א", "ב"]
