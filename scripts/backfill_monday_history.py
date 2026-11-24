#!/usr/bin/env python3
"""השלמת לוג הפעילות של מאנדיי ללוח שכבר הועבר — בלי לגעת בפריטים.

Add a monday board's activity log to a board that is already here, for the
boards that came across before the log could be exported whole.

monday's `activity_logs` answers at most 10,000 rows to any one query, and says
nothing about there being more. Every board migrated before that was found came
across with its log truncated to those 10,000 — board 266 in prod holds 9,873
rows against the 154,752 monday actually has, which is 94% of two and a quarter
years missing, and the board looks complete because the items, the messages and
the files all are.

So this is the second pass that the first one could not do: the same AuditLog
rows the importer writes, for the same board, joined to the items that are
already there. It writes nothing else — not an item, not a column, not a
message, not a file.

The join is `tasks.item_uid`, which the importer fills with monday's own item
id. The column a row refers to is matched by TITLE against the board's columns
here, because the ids on this side were minted at import time and mean nothing
to monday. A row whose item or column cannot be matched is counted and skipped,
never guessed at.

Rows already present are left alone. "Already present" is (item, moment, field,
action) — monday's own timestamp, which both passes read from the same place,
so a re-run adds nothing and a partial run can simply be run again.

    # what would happen, touching nothing:
    ./venv/bin/python scripts/backfill_monday_history.py \
        --env prod --board 266 --file ~/Downloads/full426new.json.gz

    # and then, to write it:
    ... --apply
"""
import argparse
import gzip
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from copy_board_env import connect, database_url, one          # noqa: E402
import import_monday                                            # noqa: E402

_C = sys.stdout.isatty()
def c(t, code): return f"\033[{code}m{t}\033[0m" if _C else t
RED, YEL, GRN, DIM, BOLD, CYAN = "31", "33", "32", "2", "1", "36"

BATCH = 2000


def read_export(path):
    raw = (gzip.open(path, "rt", encoding="utf-8") if path.endswith(".gz")
           else open(path, encoding="utf-8")).read()
    return import_monday.parse(raw, 79)


def main():
    ap = argparse.ArgumentParser(description="השלמת לוג מאנדיי ללוח קיים")
    ap.add_argument("--env", choices=("qa", "prod"), required=True)
    ap.add_argument("--board", type=int, required=True, help="מספר הלוח כאן")
    ap.add_argument("--file", required=True, help="קובץ הייצוא ממאנדיי (json או json.gz)")
    ap.add_argument("--apply", action="store_true",
                    help="לכתוב בפועל (בלעדיו: רק תוכנית, החיבור לקריאה בלבד)")
    a = ap.parse_args()

    print(c(f"\n  קריאת {os.path.basename(a.file)}…", DIM), flush=True)
    parsed = read_export(a.file)
    acts = parsed.get("activity") or []
    print(f"  בקובץ {c(len(acts), BOLD)} שורות לוג, "
          f"{len(parsed['items'])} פריטים, {len(parsed['columns'])} עמודות")

    db = connect(database_url(a.env))
    if not a.apply:
        db.set_session(readonly=True)
    cur = db.cursor()
    try:
        b = one(db, "select id, name, settings from boards where id=%s", (a.board,))
        if not b:
            sys.exit(f"אין לוח {a.board} ב-{a.env}")
        print(f"  הלוח כאן: {c(b['name'], BOLD)} (#{a.board}, {a.env})")

        # items: monday's id -> the task here
        cur.execute("select item_uid, id from tasks where board_id=%s "
                    "and item_uid is not null", (a.board,))
        by_uid = {str(k): v for k, v in cur.fetchall()}

        # columns: matched by title, because the ids here were minted at import
        cols_here = ((b["settings"] or {}).get("columns") or [])
        title_to_id = {}
        for col in cols_here:
            title_to_id.setdefault((col.get("title") or "").strip(), col.get("id"))
        mon_col_title = {col["key"]: (col.get("title") or "").strip()
                         for col in parsed["columns"]}

        # people: email first, then name
        cur.execute("select lower(email), id from users where email is not null")
        by_person = dict(cur.fetchall())
        cur.execute("select lower(name), id from users where name is not null")
        for k, v in cur.fetchall():
            by_person.setdefault(k, v)

        # what is already here, by monday's own moment
        cur.execute("""select a.entity_id, a.created_at, a.field_name, a.action
                       from audit_logs a
                       where a.entity_type='task'
                         and a.entity_id in (select id from tasks where board_id=%s)""",
                    (a.board,))
        have = {(r[0], r[1], r[2], r[3]) for r in cur.fetchall()}
        print(f"  כבר בלוח: {c(len(have), BOLD)} שורות לוג")

        enc = lambda v: json.dumps(v, ensure_ascii=False) if v not in (None, "") else None
        rows, skip_item, skip_col, dup, nameless = [], 0, 0, 0, 0
        seen = set()
        for r in acts:
            tid = by_uid.get(str(r.get("item") or ""))
            if tid is None:
                skip_item += 1
                continue
            field = r.get("field")
            if field == "column":
                title = mon_col_title.get(r.get("column") or "")
                cid = title_to_id.get(title) if title else None
                if not cid:
                    skip_col += 1
                    continue
                field = "col:" + cid
            when = None
            if r.get("at"):
                try:
                    when = datetime.fromisoformat(str(r["at"]).replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    when = None
            if when is None:
                skip_item += 1
                continue
            action = r.get("action") or "update"
            key = (tid, when, field, action)
            if key in have or key in seen:
                dup += 1
                continue
            seen.add(key)
            uid = (by_person.get((r.get("email") or "").lower())
                   or by_person.get((r.get("author") or "").lower()))
            if not uid:
                nameless += 1
            rows.append((tid, field, enc(r.get("old")), enc(r.get("new")), uid, action, when,
                         json.dumps({"source": "monday", "event": (r.get("event") or "")[:40],
                                     "author": (r.get("author") or "")[:120],
                                     "matched": bool(uid)}, ensure_ascii=False)))

        print()
        print(f"  {c('להוסיף', BOLD)}            {c(len(rows), GRN)}")
        print(f"  כבר קיימות      {dup}")
        print(f"  פריט לא נמצא    {skip_item}")
        print(f"  עמודה לא נמצאה  {skip_col}")
        print(f"  בלי שם מזוהה    {nameless}  {c('(השם נשמר בשורה עצמה)', DIM)}")
        if rows:
            lo, hi = min(r[6] for r in rows), max(r[6] for r in rows)
            print(f"  טווח התאריכים   {lo:%d.%m.%Y} → {hi:%d.%m.%Y}")

        if not a.apply:
            print(c("\n  תוכנית בלבד — לא נכתב כלום. להוספה בפועל: --apply\n", YEL))
            return 0
        if not rows:
            print(c("\n  אין מה להוסיף.\n", GRN))
            return 0

        from psycopg2.extras import execute_values
        for i in range(0, len(rows), BATCH):
            execute_values(cur,
                "insert into audit_logs (entity_type, entity_id, field_name, old_value,"
                " new_value, changed_by, action, created_at, origin) values %s",
                [("task",) + r for r in rows[i:i + BATCH]],
                template="(%s,%s,%s,%s,%s,%s,%s,%s,%s)")
            db.commit()
            print(c(f"    {min(i + BATCH, len(rows))}/{len(rows)}", DIM), flush=True)
        print(c(f"\n  ✓ נוספו {len(rows)} שורות ללוח {a.board} ב-{a.env}\n", GRN))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
