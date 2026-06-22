#!/usr/bin/env python3
"""Import the monday.com CSV export as a CityOS board. Idempotent — re-running
replaces the board's groups+tasks. Usage:
    python import_board.py            # import
    python import_board.py --inspect  # just print structure
"""
import csv, sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
from sqlalchemy.orm import Session
from models import init_db, Board, Group, Task, Department, TaskStatus, Priority, BoardType

SRC = "/mnt/c/Users/97252/Downloads/גיליון ללא שם - סטטוס פיתוח לוחות במערכת קוד קל.csv"
BOARD_NAME = "פיתוח לוחות עירוניים — קוד קל"
DB_PATH = os.path.join(os.path.dirname(__file__), "cityos.db")

# monday "סטטוס ביצוע" -> (enum status, label kept for display, color)
MON_STATUS = {
    "נערך אפיון":  (TaskStatus.REVIEW, "נערך אפיון", "#579bfc"),
    "בפיתוח":      (TaskStatus.IN_PROGRESS, "בפיתוח", "#fdab3d"),
    "הושלם":       (TaskStatus.DONE, "הושלם", "#00c875"),
    "ממתין":       (TaskStatus.ON_HOLD, "ממתין", "#808080"),
}
def map_status(s):
    s = (s or "").strip()
    return MON_STATUS.get(s, (TaskStatus.TODO, s or "לביצוע", "#c4c4c4"))

def split_tags(s):
    return [t.strip() for t in re.split(r"[,،/]", s or "") if t.strip()]

def read_rows(path):
    if not os.path.exists(path):
        raise RuntimeError(f"file not found: {path}")
    for enc in ("utf-8-sig", "utf-8", "cp1255"):
        try:
            with open(path, encoding=enc, newline="") as f:
                rows = list(csv.reader(f))
            if rows and any("Name" in (c or "") for r in rows[:4] for c in r):
                return rows, enc
        except Exception:
            continue
    raise RuntimeError("could not decode CSV")

def hdr_index(rows):
    for i, r in enumerate(rows[:5]):
        if any(c == "Name" for c in r):
            return i
    return 0

def parse_items(rows):
    hi = hdr_index(rows)
    items = []
    for r in rows[hi+1:]:
        if not r or not (r[0] or "").strip():
            continue
        g = lambda i: (r[i].strip() if len(r) > i and r[i] else "")
        items.append({
            "name": g(0), "interfaces": g(2), "source": g(3), "db_files": g(4),
            "link": g(5), "file_desc": g(6), "needs": g(7), "codecal_dev": g(8),
            "status_raw": g(9), "partners": g(10), "next_step": g(11), "agent": g(12),
        })
    return items

def theme(name):
    return "הסעות תלמידים" if "הסע" in name else "מערכות חינוך ונתונים"

def run_import():
    rows, enc = read_rows(SRC)
    items = parse_items(rows)
    engine = init_db(f"sqlite:///{DB_PATH}")
    with Session(engine) as db:
        dept = db.query(Department).filter(Department.name.like("%מידע%")).first() or db.query(Department).first()
        board = db.query(Board).filter(Board.name == BOARD_NAME).first()
        if board:
            for t in db.query(Task).filter(Task.board_id == board.id).all(): db.delete(t)
            for g in db.query(Group).filter(Group.board_id == board.id).all(): db.delete(g)
            db.commit()
        else:
            board = Board(name=BOARD_NAME, board_type=BoardType.LIST, icon="🧩",
                          color="#0073ea", department_id=dept.id if dept else None,
                          description="ייבוא מ-monday.com — סטטוס פיתוח לוחות (עיריית מודיעין)")
            db.add(board); db.commit()

        # groups by theme
        themes = {}
        for pos, name in enumerate(["מערכות חינוך ונתונים", "הסעות תלמידים"]):
            grp = Group(board_id=board.id, name=name, position=pos,
                        color="#0073ea" if pos == 0 else "#00c875", task_status=TaskStatus.REVIEW)
            db.add(grp); db.commit(); themes[name] = grp.id

        for pos, it in enumerate(items):
            status, label, color = map_status(it["status_raw"])
            desc = " | ".join(x for x in [it["file_desc"], it["needs"]] if x)
            tags = split_tags(it["partners"]) or ([it["interfaces"]] if it["interfaces"] else [])
            task = Task(
                board_id=board.id, group_id=themes[theme(it["name"])],
                title=it["name"], description=desc, status=status,
                priority=Priority.HIGH if "חירום" in it["name"] else Priority.MEDIUM,
                position=pos, tags=tags,
                custom_fields={
                    "status_label": label, "status_color": color,
                    "interfaces": it["interfaces"], "source_systems": it["source"],
                    "db_files": it["db_files"], "link": it["link"],
                    "needs": it["needs"], "codecal_dev": it["codecal_dev"],
                    "next_step": it["next_step"], "agent": it["agent"],
                },
            )
            db.add(task)
        db.commit()
        n = db.query(Task).filter(Task.board_id == board.id).count()
        print(f"✓ imported board '{BOARD_NAME}' (id={board.id}) with {n} items, enc={enc}")

if __name__ == "__main__":
    if "--inspect" in sys.argv:
        rows, enc = read_rows(SRC)
        print("encoding:", enc, "rows:", len(rows))
        for it in parse_items(rows):
            print(" •", it["name"], "|", it["status_raw"], "|", it["partners"])
    else:
        run_import()
