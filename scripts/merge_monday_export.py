#!/usr/bin/env python3
"""
Merge a monday.com export into the one file the board importer reads.

The export arrives in pieces, because one request cannot carry it all: the
board (name, groups, column definitions, first 500 items), one more page per
cursor beyond those 500, and the history — `activity_logs` together with the
account's user list — which does not fit beside the items. The import reads
them as the one board they describe, as long as they sit in a single JSON
array:

    [ {the board response}, {the history response}, {page 2}, {page 3} ]

The merge is the wrapper and nothing else — `[`, a comma, `]`. It does not
repair a response that came back wrong, and a stale response mixed in with a
fresh one produces a file that looks perfectly fine. So everything that can be
checked before the upload is checked here: that exactly one board brought the
items, that no page was left behind a cursor, that the history belongs to that
same board, that the user list came along, and whether the file links have
already expired. See docs/MONDAY_EXPORT_IMPORT.md.

Usage:
  python scripts/merge_monday_export.py board.json log.json
  python scripts/merge_monday_export.py resp*.json -o ~/Downloads/merged353.json
  python scripts/merge_monday_export.py merged353.json --check   # check, write nothing

Exit code: 0 = ready to upload, 1 = a problem the import would hit, 2 = could
not read a file.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

_C = sys.stdout.isatty()
def c(t, code): return f"\033[{code}m{t}\033[0m" if _C else t
RED, YEL, GRN, DIM, BOLD, CYAN = "31", "33", "32", "2", "1", "36"

LOG_PAGE = 10000        # the history query's ceiling; exactly this many means ask for page 2
ITEM_PAGE = 500         # the items query's page size
_URL = re.compile(r"X-Amz-Date=(\d{8}T\d{6}Z)[^\"]*?X-Amz-Expires=(\d+)")


def load(path):
    """Every response in one file — a file that is already a merge counts as its parts."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return doc if isinstance(doc, list) else [doc]


def expiry(raw):
    """When the signed file links in this text stop working, or None if it holds none.

    monday signs `assets { public_url }` for an hour and writes the hour inside
    the link itself. An export that sat on disk overnight arrives with the file
    names and without the bytes.
    """
    m = _URL.search(raw)
    if not m:
        return None
    signed = dt.datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    return signed + dt.timedelta(seconds=int(m.group(2)))


def when(t):
    """A time, with the date added once it is not today — an export from
    yesterday whose links read "11:20" looks like an hour from now."""
    t = t.astimezone()
    return f"{t:%H:%M}" if t.date() == dt.date.today() else f"{t:%d.%m %H:%M}"


def describe(resp):
    """What one response brought."""
    data = (resp.get("data") or {}) if isinstance(resp, dict) else {}
    out = {"items": 0, "pages": 0, "cursors": [], "logs": 0, "log_pages": [],
           "users": len(data.get("users") or []), "count": None,
           "with_items": set(), "without_items": set(), "logs_of": set(),
           "errors": [e.get("message", "") for e in (resp.get("errors") or [])
                      if isinstance(e, dict)] if isinstance(resp, dict) else []}

    def page(items, cursor):
        out["pages"] += 1
        out["items"] += len(items)
        out["cursors"].append(cursor)

    for b in data.get("boards") or []:
        bid = str(b.get("id"))
        # monday's own answer to "how many rows does this board have". It rides
        # on the response that asked for the board itself, which is page one.
        if out["count"] is None and isinstance(b.get("items_count"), int):
            out["count"] = b["items_count"]
        box = b.get("items_page") if isinstance(b.get("items_page"), dict) else None
        items = (box or {}).get("items") if box else b.get("items")
        if isinstance(items, list):
            out["with_items"].add(bid)
            page(items, (box or {}).get("cursor"))
        else:
            out["without_items"].add(bid)
        if isinstance(b.get("activity_logs"), list):
            out["logs"] += len(b["activity_logs"])
            out["log_pages"].append(len(b["activity_logs"]))
            out["logs_of"].add(bid)
    nxt = data.get("next_items_page")
    if isinstance(nxt, dict) and isinstance(nxt.get("items"), list):
        page(nxt["items"], nxt.get("cursor"))      # a page fetched by cursor has no board around it
    return out


def report(parts):
    """Print what each response brought; return the problems and the warnings."""
    total = {"items": 0, "pages": 0, "logs": 0, "users": 0, "cursors": [], "log_pages": [],
             "count": None, "with_items": set(), "without_items": set(), "logs_of": set()}
    seen_paths = set()
    for path, resp, soon in parts:
        d = describe(resp)
        for k in ("items", "pages", "logs"):
            total[k] += d[k]
        total["users"] = max(total["users"], d["users"])
        if total["count"] is None:
            total["count"] = d["count"]
        total["cursors"] += d["cursors"]
        total["log_pages"] += d["log_pages"]
        for k in ("with_items", "without_items", "logs_of"):
            total[k] |= d[k]

        what = []
        if d["pages"]:
            what.append(f"{d['items']} פריטים" + (f" ב-{d['pages']} עמודים" if d["pages"] > 1 else ""))
        if d["logs"]:
            what.append(f"{d['logs']} רשומות היסטוריה")
        if d["users"]:
            what.append(f"{d['users']} משתמשים")
        boards = sorted(d["with_items"] | d["without_items"] | d["logs_of"])
        shown = ", ".join(boards[:3]) + (f" ועוד {len(boards) - 3}" if len(boards) > 3 else "")
        print(f"  {c(os.path.basename(path), BOLD)} — "
              + (", ".join(what) or c("לא הביא כלום", RED))
              + (c(f"  [{'לוח' if len(boards) == 1 else 'לוחות'} {shown}]", DIM) if boards else ""))
        for msg in d["errors"]:
            print(c(f"      ✗ מאנדיי החזיר שגיאה: {msg}", RED))
        if soon and path not in seen_paths:
            print(c(f"      קישורי הקבצים בקובץ הזה תקפים עד {when(soon)}", DIM))
        seen_paths.add(path)

    problems, warnings = [], []
    if not total["with_items"]:
        problems.append("אף תשובה לא הביאה פריטים — הייבוא דורש לוח עם פריטים")
    elif len(total["with_items"]) > 1:
        problems.append("יותר מלוח אחד הביא פריטים: " + ", ".join(sorted(total["with_items"]))
                        + " — ייבוא אחד בונה לוח אחד. כנראה בקשה שרצה בלי boardId")
    board = next(iter(total["with_items"]), None)

    # Each non-null cursor should have been consumed by a page that followed it.
    # As many cursors as pages means the chain ended with a cursor still set:
    # the export stopped mid-board, and that is the one thing a migration must
    # not discover later.
    live = [x for x in total["cursors"] if x]
    if live and len(live) >= total["pages"]:
        problems.append(f"הייצוא נעצר באמצע הלוח — נשאר cursor פתוח אחרי {total['items']} פריטים. "
                        "הריצי את בקשה 3 עם ה-cursor עד שיחזור null, והוסיפי כל תשובה לאיחוד")

    # The arithmetic the cursor check cannot do. A chain of pages that ends on a
    # null cursor is a chain that ran to the end of SOMETHING — it does not say
    # the pages in between are all here. A merge assembled by hand, or by a
    # glob that missed a file, loses a page out of the middle and the last page
    # still closes cleanly. monday states the board's row count on page one, and
    # that is the only number in the file that can contradict the file.
    if total["count"] is not None and total["items"] < total["count"]:
        problems.append(
            f"בקובץ {total['items']} פריטים, והלוח במאנדיי מחזיק {total['count']} — "
            f"חסרים {total['count'] - total['items']}. אם יש פער בלי cursor פתוח, "
            "כנראה אחד מעמודי ההמשך לא נכנס לאיחוד: בדקי שכל קובצי התשובה נמסרו לסקריפט")

    strangers = sorted((total["without_items"] | total["logs_of"]) - {board}) if board else []
    if strangers:
        warnings.append(f"בקובץ יש עוד {len(strangers)} לוחות ({', '.join(strangers[:3])}"
                        + (", ..." if len(strangers) > 3 else "")
                        + ") — בקשה שרצה בלי boardId. הייבוא ישמיט אותם, אבל ההיסטוריה של הלוח שלך "
                          "אולי לא בקובץ בכלל")
    if board and board not in total["logs_of"]:
        warnings.append("אין בקובץ היסטוריה של הלוח — הלוח ייובא בלי לוג. "
                        "אם רצתה היסטוריה, זו בקשה 2 עם boardId")
    if any(n >= LOG_PAGE for n in total["log_pages"]):
        warnings.append(f"עמוד היסטוריה חזר עם {LOG_PAGE} רשומות בדיוק — זו תקרת השאילתה, "
                        "כנראה יש עוד. הריצי את בקשה 2 עם page הבא; אם חזר [] יש הכל")
    if total["logs"] and not total["users"]:
        warnings.append("יש היסטוריה בלי רשימת משתמשים — כל שורה בלוג תירשם על \"מערכת\". "
                        "הוסיפי users { id name email } לשאילתה")
    # A guess at the question items_count answers outright, and worth making
    # only when the file never carried the answer: an export that asked for
    # `items_count` has already been checked against it above.
    if total["count"] is None and total["items"] % ITEM_PAGE == 0 and total["items"] and not live:
        warnings.append(f"מספר הפריטים ({total['items']}) הוא כפולה מדויקת של {ITEM_PAGE} — "
                        "שווה לוודא שבאמת זה מספר הפריטים בלוח במאנדיי. "
                        f"שאילתה שמבקשת גם items_count עונה על זה מעצמה")

    print()
    whole = ("" if total["count"] is None
             else c(f" מתוך {total['count']} בלוח", GRN if total["items"] >= total["count"] else RED))
    print(f"  סה\"כ: {c(str(total['items']), BOLD)} פריטים{whole} · "
          f"{c(str(total['logs']), BOLD)} רשומות היסטוריה · "
          f"{c(str(total['users']), BOLD)} משתמשים · לוח "
          + (c(board, CYAN) if board else c("—", RED)))
    return problems, warnings


def main():
    ap = argparse.ArgumentParser(
        description="איחוד תשובות הייצוא ממאנדיי לקובץ אחד, עם הבדיקות שלפני ההעלאה.")
    ap.add_argument("files", nargs="+", help="תשובות הייצוא: הלוח, ההיסטוריה, ועמודי ההמשך")
    ap.add_argument("-o", "--out", default="merged.json", help="קובץ היעד (ברירת מחדל: merged.json)")
    ap.add_argument("--check", action="store_true", help="רק לבדוק, בלי לכתוב קובץ")
    ap.add_argument("--force", action="store_true", help="לדרוס קובץ יעד קיים")
    args = ap.parse_args()

    parts = []
    for path in args.files:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
            doc = json.loads(raw)
        except FileNotFoundError:
            print(c(f"✗ אין קובץ כזה: {path}", RED)); sys.exit(2)
        except json.JSONDecodeError as e:
            print(c(f"✗ {path} אינו JSON תקין: {e}", RED))
            print(c("  תשובה שנשמרה מ-Postman באמצע ההורדה תיראה בדיוק כך — שמרי אותה שוב.", DIM))
            sys.exit(2)
        soon = expiry(raw)
        for resp in (doc if isinstance(doc, list) else [doc]):
            parts.append((path, resp, soon))

    print(f"\n{c('מה יש בקבצים', BOLD)}")
    problems, warnings = report(parts)

    expiries = [s for _, _, s in parts if s]
    if expiries:
        soonest = min(expiries)
        left = (soonest - dt.datetime.now(dt.timezone.utc)).total_seconds()
        if left <= 0:
            warnings.append(f"קישורי הקבצים פגו ב-{when(soonest)} — "
                            "המצורפים ייובאו כשמות בלי התוכן. אם הם חשובים, ייצאי שוב וייבאי מיד")
        elif left < 15 * 60:
            warnings.append(f"קישורי הקבצים פגים ב-{when(soonest)} — "
                            f"נשארו {int(left // 60)} דקות להעלות")

    for w in warnings:
        print(c(f"  ⚠ {w}", YEL))
    for p in problems:
        print(c(f"  ✗ {p}", RED))

    if problems:
        print(c("\nלא נכתב קובץ. תקני את מה שמסומן ב-✗ והריצי שוב.\n", RED))
        sys.exit(1)
    if args.check:
        print(c("\n✓ הקובץ תקין להעלאה (--check: לא נכתב כלום)\n", GRN))
        return
    if os.path.exists(args.out) and not args.force:
        print(c(f"\n✗ {args.out} כבר קיים. בחרי שם אחר ב--out, או --force לדריסה.\n", RED))
        sys.exit(1)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump([resp for _, resp, _ in parts], fh, ensure_ascii=False)
    size = os.path.getsize(args.out) / (1024 * 1024)
    print(c(f"\n✓ נכתב {args.out} — {len(parts)} תשובות, {size:.1f}MB", GRN))
    print("  להעלאה: + בסייד-בר → לוח → יצירת לוח מקובץ\n")


if __name__ == "__main__":
    main()
