#!/usr/bin/env python3
"""
Re-sign the attachment links inside a monday export that has gone stale.

monday hands out one pre-signed link per attachment and signs it for an hour,
with the hour written inside the link itself (`X-Amz-Date` + `X-Amz-Expires`).
The bytes can only be brought across while that link is alive: an export that
sat on disk arrives with the file NAMES and without the files. The signature
cannot be extended — that is what a signature is for — but the asset can be
asked for again, and monday answers with a freshly signed link to the same
file.

So nothing here repairs the old link. It fetches a new one per asset id, by the
ids the export already carries, and writes a copy of the file with the links
replaced. One small request instead of exporting the board again: no items, no
columns, no history, and the rest of the file is left exactly as it was.

An asset that was deleted in monday since the export has no new link. Those are
counted and left with the old one, because a name is still better than nothing
and the import says how many came as names.

Usage:
  export MONDAY_TOKEN=...                                  # or --token
  python scripts/refresh_monday_links.py merged285.json -o merged285-fresh.json
  python scripts/refresh_monday_links.py merged285.json --check   # no token, no calls

Exit code: 0 = done, 1 = nothing to refresh or a problem, 2 = could not read.
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.monday.com/v2"
API_VERSION = "2024-10"
BATCH = 100          # asset ids per request; the query is cheap, the URL is not the limit
QUERY = "query($ids: [ID!]!) { assets(ids: $ids) { id name public_url } }"

_C = sys.stdout.isatty()
def c(t, code): return f"\033[{code}m{t}\033[0m" if _C else t
RED, YEL, GRN, DIM, BOLD, CYAN = "31", "33", "32", "2", "1", "36"


def expiry(url):
    """When this pre-signed link lapses, or None if it is not a signed link."""
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url or "").query)
        minted = (q.get("X-Amz-Date") or [""])[0]
        window = int((q.get("X-Amz-Expires") or ["0"])[0])
        if not minted or window <= 0:
            return None
        t = dt.datetime.strptime(minted, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        return t + dt.timedelta(seconds=window)
    except (ValueError, TypeError, OverflowError):
        return None


def when(t):
    t = t.astimezone()
    return f"{t:%H:%M}" if t.date() == dt.date.today() else f"{t:%d.%m %H:%M}"


def assets_in(node, found=None):
    """Every asset in the file: anything carrying both an id and a public_url.

    Walking for the shape rather than the path is what makes this work on all
    four places an export puts attachments — the item, a file cell, an update
    and a reply to one — without the walk having to know they exist.
    """
    found = [] if found is None else found
    if isinstance(node, dict):
        if "public_url" in node and node.get("id") is not None:
            found.append(node)
        for v in node.values():
            assets_in(v, found)
    elif isinstance(node, list):
        for v in node:
            assets_in(v, found)
    return found


def ask(ids, token):
    """monday's answer for one batch of asset ids: {id: public_url}."""
    body = json.dumps({"query": QUERY, "variables": {"ids": list(ids)}}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": token,
        "API-Version": API_VERSION,
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            doc = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(c(f"✗ מאנדיי ענה {e.code} — "
                           + ("הטוקן לא תקף" if e.code in (401, 403) else e.reason or ""), RED))
    except urllib.error.URLError as e:
        raise SystemExit(c(f"✗ אין תשובה ממאנדיי: {e.reason}", RED))
    # monday answers an error with HTTP 200 and an `errors` array, which is the
    # one failure worth printing in full: it names the field it refused.
    for e in doc.get("errors") or []:
        print(c(f"  ✗ {e.get('message', '')}", RED))
    if doc.get("errors") and not (doc.get("data") or {}).get("assets"):
        raise SystemExit(1)
    return {str(a["id"]): a.get("public_url") or ""
            for a in ((doc.get("data") or {}).get("assets") or []) if a.get("id")}


def main():
    ap = argparse.ArgumentParser(
        description="החזרת תוקף לקישורי המצורפים בקובץ ייצוא ממאנדיי.")
    ap.add_argument("file", help="הקובץ המאוחד (או תשובת ייצוא בודדת)")
    ap.add_argument("-o", "--out", help="קובץ היעד (ברירת מחדל: <שם>-fresh.json)")
    ap.add_argument("--token", default=os.getenv("MONDAY_TOKEN", ""),
                    help="טוקן מאנדיי; ברירת מחדל מתוך MONDAY_TOKEN")
    ap.add_argument("--check", action="store_true", help="רק להראות מה יש בקובץ, בלי פנייה למאנדיי")
    ap.add_argument("--force", action="store_true", help="לדרוס קובץ יעד קיים")
    args = ap.parse_args()

    try:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        print(c(f"✗ אין קובץ כזה: {args.file}", RED)); sys.exit(2)
    except json.JSONDecodeError as e:
        print(c(f"✗ {args.file} אינו JSON תקין: {e}", RED)); sys.exit(2)

    assets = assets_in(doc)
    if not assets:
        print(c(f"\nאין מצורפים ב-{os.path.basename(args.file)} — אין מה לרענן.\n", YEL))
        sys.exit(1)

    now = dt.datetime.now(dt.timezone.utc)
    times = [t for t in (expiry(a.get("public_url")) for a in assets) if t]
    dead = sum(1 for t in times if t <= now)
    ids = sorted({str(a["id"]) for a in assets})
    print(f"\n  {c(os.path.basename(args.file), BOLD)} — {len(assets)} מצורפים, "
          f"{len(ids)} קבצים שונים")
    if times:
        edge = min(times) if dead else max(times)
        print("  " + (c(f"הקישורים פגו ב-{when(edge)}", YEL) if dead
                      else c(f"הקישורים עוד תקפים עד {when(edge)}", GRN)))

    if args.check:
        print(c("\n(--check: לא נכתב כלום ולא נשלחה בקשה)\n", DIM))
        return
    if not args.token:
        print(c("\n✗ אין טוקן. export MONDAY_TOKEN=... או --token\n", RED)); sys.exit(1)

    fresh = {}
    for i in range(0, len(ids), BATCH):
        batch = ids[i:i + BATCH]
        print(c(f"  מבקש קישורים חדשים… {i + len(batch)}/{len(ids)}", DIM))
        fresh.update(ask(batch, args.token))

    gone = [i for i in ids if not fresh.get(i)]
    changed = 0
    for a in assets:
        new = fresh.get(str(a["id"]))
        if new and new != a.get("public_url"):
            a["public_url"] = new
            changed += 1

    out = args.out or (os.path.splitext(args.file)[0] + "-fresh.json")
    if os.path.exists(out) and not args.force:
        print(c(f"\n✗ {out} כבר קיים. בחרי שם אחר ב--out, או --force לדריסה.\n", RED)); sys.exit(1)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)

    good = [t for t in (expiry(a.get("public_url")) for a in assets) if t and t > now]
    print(c(f"\n✓ נכתב {out} — {changed} קישורים הוחלפו", GRN))
    if good:
        print(c(f"  תקפים עד {when(min(good))} — זה הזמן להעלות", CYAN))
    if gone:
        print(c(f"  ⚠ {len(gone)} קבצים לא קיימים יותר במאנדיי ונשארו עם השם בלבד", YEL))
    print("  להעלאה: + בסייד-בר → לוח → יצירת לוח מקובץ\n")


if __name__ == "__main__":
    main()
