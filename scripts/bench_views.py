#!/usr/bin/env python3
"""מדידת בסיס לתצוגות הטבלה — מספרים, לא יעדים.

"אין להמציא יעד זמן בלי מדידת בסיס." So this measures and prints; it asserts
nothing about how long anything ought to take. Run it before changing the
query path and again after, and compare the two runs — that is what makes a
number mean something.

Picks two boards out of whatever database it is pointed at: the one closest to
40 items (a representative board) and the largest live one. Deleted and
archived boards are skipped — they cannot be opened, so timing them measures
the 404.

    ./venv/bin/python scripts/bench_views.py

Each row is min / median / max over seven runs. Min is the honest number for
comparing two versions of the code; max catches the first-run cost of anything
being warmed.
"""
import pathlib, statistics, sys, time
ROOT = pathlib.Path('.').resolve()
sys.path.insert(0, str(ROOT / 'backend'))
import main as m
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import Board, Task, SavedView
from fastapi.testclient import TestClient

c = TestClient(m.app, headers={'host':'localhost'})
with Session(m.engine) as db:
    admin = db.query(m.User).filter(m.User.role == 'admin').first().id
    sizes = (db.query(Board.id, func.count(Task.id))
               .join(Task, Task.board_id == Board.id)
               .filter(Task.deleted_at.is_(None), Task.parent_id.is_(None),
                       Board.deleted_at.is_(None), Board.is_archived == False)
               .group_by(Board.id).order_by(func.count(Task.id).desc()).all())
    cols_of = {b.id: len((b.settings or {}).get('columns') or [])
               for b in db.query(Board).all()}

big = sizes[0]
mid = min(sizes, key=lambda r: abs(r[1] - 40))
H = {'X-CityOS-User': str(admin)}

ADV = {"op": "and", "rules": [{"field": "status", "op": "ne", "v": "done"}]}

def timed(fn, n=7):
    xs = []
    for _ in range(n):
        t = time.perf_counter(); fn(); xs.append((time.perf_counter() - t) * 1000)
    return min(xs), statistics.median(xs), max(xs)

def q(bid, **body):
    r = c.post(f"/api/boards/{bid}/items/query",
               json=dict({"user_id": admin, "today": "2026-10-20", "tz_offset": 180}, **body),
               headers=H)
    assert r.status_code == 200, r.text
    return r.json()

print(f"{'board':>6} {'items':>6} {'cols':>5}  {'what':<34} {'min':>8} {'med':>8} {'max':>8}")
for bid, n in (mid, big):
    nc = cols_of.get(bid, 0)
    for label, body in (
        ("open: unfiltered page",        {}),
        ("filter (adv, 1 rule)",         {"filter": ADV}),
        ("filter + search",              {"filter": ADV, "q": "א"}),
        ("filter + sort by due",         {"filter": ADV, "sort": "due"}),
        ("page 2 of a sorted filter",    {"filter": ADV, "sort": "due", "offset": 50}),
        ("ids only (whole board)",       {"filter": ADV, "ids_only": True}),
        ("one named row still matches?", {"filter": ADV, "only": [1]}),
    ):
        lo, med, hi = timed(lambda: q(bid, **body))
        print(f"{bid:>6} {n:>6} {nc:>5}  {label:<34} {lo:>7.1f}ms {med:>7.1f}ms {hi:>7.1f}ms")
    r = q(bid, filter=ADV)
    print(f"{'':>6} {'':>6} {'':>5}  → matched {r['matched']} of {r['total']} "
          f"(own {r['matched_own']}, subs {r['matched_subs']}, context {r['matched_context']}), "
          f"page held {len(r['items'])}")
    print()

# the strip itself
for bid, n in (mid, big):
    lo, med, hi = timed(lambda: c.get(f"/api/boards/{bid}/views?user_id={admin}", headers=H))
    print(f"{bid:>6} {n:>6} {cols_of.get(bid,0):>5}  {'list views (the strip)':<34} "
          f"{lo:>7.1f}ms {med:>7.1f}ms {hi:>7.1f}ms")
