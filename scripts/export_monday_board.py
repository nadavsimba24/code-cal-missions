#!/usr/bin/env python3
"""
Run a monday.com board export end to end: every request, every page, one file.

Postman does this by hand today — send request 1, read the cursor, send request
3 with it, send it again, walk the history page by page, save each response,
then merge them. It works, and every step of it is a place to lose a page: a
response saved half-downloaded, a cursor copied with a character missing, a
second board's log collected because a variable was left empty. The export that
started all of this was produced by a saved collection two revisions behind.

Nothing here is new behaviour. It is the same three queries, run in order, with
the cursors carried for you — and the queries are READ FROM
backend/monday_export.graphql rather than copied into this file, so the export
and the importer can never drift apart. The merge and its checks are the
existing script's: this hands the responses to merge_monday_export.py and lets
it say whether the file is fit to upload.

Usage:
  export MONDAY_TOKEN=...                       # monday → Developers → My access tokens
  python scripts/export_monday_board.py 6204255781
  python scripts/export_monday_board.py 6204255781 7310442190 -d ~/Downloads
  python scripts/export_monday_board.py 6204255781 --no-history   # items only
  python scripts/export_monday_board.py --dry-run 6204255781      # what it would ask for

One file per board, named monday-<id>.json, ready to upload in the app.

Exit code: 0 = every board came out whole, 1 = something a later import would
hit, 2 = could not run (no token, no query file).
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.monday.com/v2"
API_VERSION = "2024-10"
HERE = pathlib.Path(__file__).resolve().parent
GRAPHQL = HERE.parent / "backend" / "monday_export.graphql"
MERGE = HERE / "merge_monday_export.py"

_C = sys.stdout.isatty()
def c(t, code): return f"\033[{code}m{t}\033[0m" if _C else t
RED, YEL, GRN, DIM, BOLD, CYAN = "31", "33", "32", "2", "1", "36"

# monday's ceiling for one request, and the one this walks the log against.
# A refusal for complexity halves the page rather than giving up: the walk is
# unchanged by a smaller page, only longer.
LOG_LIMIT = 10000
LOG_MIN = 625
# The log has no count — no activity_logs_count beside the board's items_count —
# so the only way to know where it ends is to ask for a page and see it come
# back short. A ceiling on the walk so a misread never turns into a loop.
LOG_MAX_PAGES = 60
ITEM_MAX_PAGES = 200
# monday meters complexity per minute. A pause between pages costs a few seconds
# on a big board and is the difference between finishing and being throttled
# halfway, which looks exactly like a board that is smaller than it is.
PAUSE = 0.4


# ── the queries, read from the file the importer documents ─────────────────
# Split on the same banners tests/test_import_query.py splits on. If that file
# is reorganised this stops rather than sending something half-recognised.
_BANNERS = r"page one|the history, as a request of its own|every page after it"


def queries():
    try:
        src = GRAPHQL.read_text(encoding="utf-8")
    except OSError as e:
        print(c(f"✗ לא ניתן לקרוא את {GRAPHQL}: {e}", RED)); sys.exit(2)
    parts = re.split(r"^# ── (?:" + _BANNERS + r") ─+\n", src, flags=re.M)
    if len(parts) != 4:
        print(c("✗ backend/monday_export.graphql אינו מחזיק את שלוש השאילתות המוכרות", RED))
        print(c("  הקובץ שונה — ערכי את הסקריפט במקום לשלוח שאילתה חלקית.", DIM))
        sys.exit(2)
    out = []
    for block in parts[1:]:
        lines = block.splitlines()
        while lines and (lines[0].startswith("#") or not lines[0].strip()):
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        out.append("\n".join(lines))
    return out                      # page one, the history, every page after


# ── the one HTTP call ──────────────────────────────────────────────────────
class Refused(Exception):
    """monday answered, and the answer was a refusal naming its reason."""


def ask(query, variables, token, label):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": token,
        "API-Version": API_VERSION,
    })
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            doc = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = (e.read() or b"")[:300].decode("utf-8", "replace")
        except Exception:
            pass
        if e.code in (401, 403):
            print(c("✗ מאנדיי דחה את הטוקן (401/403). צרי טוקן חדש ב-Developers → My access tokens.",
                    RED))
            sys.exit(2)
        raise Refused(f"HTTP {e.code} {detail}")
    except urllib.error.URLError as e:
        raise Refused(f"אין תשובה ממאנדיי: {e.reason}")
    # An error from monday arrives as HTTP 200 with an `errors` array. A
    # response read for `data` alone looks like an empty board.
    errs = [str(e.get("message", "")) for e in (doc.get("errors") or [])]
    if errs and not doc.get("data"):
        raise Refused("; ".join(errs))
    for m in errs:
        print(c(f"      ⚠ {label}: {m}", YEL))
    return doc


def _complexity(err):
    return "COMPLEXITY" in str(err).upper() or "complexity" in str(err)


# ── one board ──────────────────────────────────────────────────────────────
def export_board(board_id, token, q1, qlog, qnext, want_history=True, dry=False):
    """Every response this board is made of, in the order they were asked for."""
    parts, label = [], c(f"לוח {board_id}", BOLD)
    print(f"\n{label}")
    if dry:
        print(c(f"  היה שולח: עמוד הפריטים הראשון, עמודי ההמשך, ו{'היסטוריה' if want_history else 'בלי היסטוריה'}",
                DIM))
        return parts, []

    problems = []

    # ── the board, and its first 500 items ──
    doc = ask(q1, {"boardId": [str(board_id)]}, token, "עמוד 1")
    boards = ((doc.get("data") or {}).get("boards") or [])
    if not boards:
        problems.append(f"לוח {board_id}: מאנדיי לא החזיר אותו — בדקי את המספר ואת ההרשאה לטוקן")
        print(c(f"  ✗ {problems[-1]}", RED))
        return parts, problems
    b = boards[0]
    page = b.get("items_page") or {}
    got, want = len(page.get("items") or []), b.get("items_count")
    parts.append(doc)
    print(f"  {c('✓', GRN)} \"{b.get('name') or ''}\" — {got}"
          + (f" מתוך {want}" if want is not None else "") + " פריטים, "
          + f"{len(b.get('groups') or [])} קבוצות, {len(b.get('columns') or [])} עמודות")

    # ── every page after the first, by the cursor the last one returned ──
    cursor, n = page.get("cursor"), 1
    while cursor and n < ITEM_MAX_PAGES:
        time.sleep(PAUSE)
        n += 1
        doc = ask(qnext, {"cursor": cursor}, token, f"עמוד {n}")
        nxt = ((doc.get("data") or {}).get("next_items_page") or {})
        came = len(nxt.get("items") or [])
        parts.append(doc)
        got += came
        print(f"  {c('✓', GRN)} עמוד {n}: {came} פריטים (סך הכל {got}"
              + (f" מתוך {want}" if want is not None else "") + ")")
        cursor = nxt.get("cursor")
    if cursor:
        problems.append(f"לוח {board_id}: נעצר אחרי {ITEM_MAX_PAGES} עמודים ועוד נשארו פריטים")
        print(c(f"  ✗ {problems[-1]}", RED))
    elif want is not None and got < want:
        # Not an assertion — monday's items_count can include items a filter or
        # a permission keeps out of the pages. Said, not decided.
        print(c(f"  ⚠ הגיעו {got} מתוך {want} ש-items_count מדווח", YEL))

    if not want_history:
        return parts, problems

    # ── the history, page by page, with no count to walk against ──
    limit, pg, total = LOG_LIMIT, 1, 0
    while pg <= LOG_MAX_PAGES:
        time.sleep(PAUSE)
        q = qlog.replace(f"activity_logs(limit: {LOG_LIMIT}", f"activity_logs(limit: {limit}")
        try:
            doc = ask(q, {"boardId": [str(board_id)], "page": pg}, token, f"היסטוריה, עמוד {pg}")
        except Refused as e:
            if _complexity(e) and limit > LOG_MIN:
                limit //= 2
                print(c(f"  ⚠ עמוד ההיסטוריה גדול מדי למאנדיי — ממשיך ב-{limit} רשומות לעמוד", YEL))
                continue
            raise
        logs = (((doc.get("data") or {}).get("boards") or [{}])[0] or {}).get("activity_logs") or []
        parts.append(doc)
        total += len(logs)
        print(f"  {c('✓', GRN)} היסטוריה, עמוד {pg}: {len(logs)} רשומות (סך הכל {total})")
        if len(logs) < limit:
            break
        pg += 1
    else:
        problems.append(f"לוח {board_id}: ההיסטוריה נעצרה אחרי {LOG_MAX_PAGES} עמודים")
        print(c(f"  ✗ {problems[-1]}", RED))
    if not total:
        # Worth saying out loud: monday keeps the log for a window that depends
        # on the plan, and an empty log is a fact about monday, not a failure.
        print(c("  ⚠ לא חזרו רשומות היסטוריה — ייתכן שהחלון של מאנדיי כבר לא מכסה את הלוח", YEL))
    return parts, problems


def main():
    ap = argparse.ArgumentParser(
        description="ייצוא לוח ממאנדיי: כל הבקשות, כל העמודים, קובץ אחד מוכן לייבוא.")
    ap.add_argument("boards", nargs="+", help="מספרי הלוחות (board id), מופרדים ברווח")
    ap.add_argument("-d", "--dir", default=".", help="לאן לכתוב (ברירת מחדל: התיקייה הנוכחית)")
    ap.add_argument("--token", default=os.environ.get("MONDAY_TOKEN", ""),
                    help="טוקן מאנדיי; ברירת מחדל MONDAY_TOKEN מהסביבה")
    ap.add_argument("--no-history", action="store_true", help="בלי activity_logs")
    ap.add_argument("--keep-parts", action="store_true",
                    help="לשמור גם כל תשובה בנפרד, לבדיקה")
    ap.add_argument("--dry-run", action="store_true", help="להראות מה היה נשלח, בלי לשלוח")
    args = ap.parse_args()

    if not args.token and not args.dry_run:
        print(c("✗ אין טוקן. export MONDAY_TOKEN=... או --token", RED))
        print(c("  מאנדיי → Developers → My access tokens. הטוקן הוא מפתח לכל החשבון —", DIM))
        print(c("  אל תכניסי אותו לקובץ שנכנס ל-git. .env מוחרג משם.", DIM))
        sys.exit(2)

    q1, qlog, qnext = queries()
    out_dir = pathlib.Path(args.dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    failed, written = [], []
    for bid in args.boards:
        if not str(bid).strip().isdigit():
            print(c(f"✗ \"{bid}\" אינו מספר לוח", RED)); failed.append(bid); continue
        try:
            parts, problems = export_board(bid, args.token, q1, qlog, qnext,
                                           want_history=not args.no_history,
                                           dry=args.dry_run)
        except Refused as e:
            print(c(f"  ✗ לוח {bid}: {e}", RED)); failed.append(bid); continue
        if args.dry_run:
            continue
        if problems:
            failed.append(bid)
        if not parts:
            continue

        if args.keep_parts:
            for i, p in enumerate(parts, 1):
                (out_dir / f"monday-{bid}-part{i}.json").write_text(
                    json.dumps(p, ensure_ascii=False), encoding="utf-8")

        # The merge is the other script's job, checks included — one place that
        # decides whether a file is fit to upload, whoever produced it.
        target = out_dir / f"monday-{bid}.json"
        target.write_text(json.dumps(parts, ensure_ascii=False), encoding="utf-8")
        written.append(target)
        print(c(f"\n  בדיקת הקובץ ({target.name})", BOLD))
        r = subprocess.run([sys.executable, str(MERGE), str(target), "--check"])
        if r.returncode != 0:
            failed.append(bid)

    if args.dry_run:
        return 0
    print()
    for t in written:
        print(f"{c('✓', GRN)} {t}")
    if failed:
        print(c(f"\n✗ {len(set(failed))} לוחות לא יצאו שלמים: {', '.join(sorted(set(map(str, failed))))}",
                RED))
        print(c("  אל תעלי אותם לפני שהבעיה שלמעלה נפתרה.", DIM))
        return 1
    print(c("\nהקבצים מוכנים להעלאה במסך הייבוא.", GRN))
    print(c("קישורי הקבצים שמאנדיי חותם חיים כשעה — אם יש נספחים, העלי עכשיו.", DIM))
    return 0


if __name__ == "__main__":
    sys.exit(main())
