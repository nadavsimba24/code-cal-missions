#!/usr/bin/env python3
"""Pull a monday board's FULL activity log, past the 10,000-row ceiling.

`activity_logs(limit: 10000, page: N)` does not paginate the way it looks like
it does. Page 1 of a busy board comes back with exactly 10,000 rows and page 2
comes back empty, so the export quietly stops at whatever the newest 10,000
happen to be. On the board that prompted this — 21,187 meeting items — that was
9,950 rows covering March to November 2026, out of 147,254 going back to
December 2023. Six per cent of the history, and nothing in the answer says so.

What monday does honour is `from` / `to`. So the way past the ceiling is to
stop asking for pages and start asking for time: take the oldest row the last
answer returned, make it the next `to`, and walk backwards until an answer
comes back short. Fifteen windows covered three years with no gap.

Rows are deduped by log id, because a window boundary lands on a timestamp and
the row sitting exactly on it comes back in both windows.

    python3 scripts/monday_history.py <boardId>            # write the files
    python3 scripts/monday_history.py <boardId> --count     # just measure

The files land in ~/Downloads as response<last3>h1.json … hN.json, newest
first, which is the order merge_monday_export.py and the importer both want:
if a ceiling does trim the history later, what survives is the recent half.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.expanduser("~/Downloads")
CEILING = 10000          # monday's, not ours
MAX_WINDOWS = 400        # a stop, so a misbehaving answer cannot loop forever


def token():
    """The export token, read from .env and never printed."""
    env = os.environ.get("MONDAY_TOKEN")
    if env:
        return env.strip()
    path = os.path.join(ROOT, ".env")
    try:
        for line in open(path, encoding="utf-8"):
            if line.startswith("MONDAY_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    sys.exit("MONDAY_TOKEN לא נמצא — לא ב-.env ולא במשתני הסביבה")


# The light query is for measuring: asking for `data` on 147,254 rows is 150MB
# of answer to find out a number.
LIGHT = """query ($b: [ID!], $t: ISO8601DateTime) {
  boards(ids: $b) { activity_logs(limit: 10000, page: 1, to: $t) { id created_at } }
}"""

# `users` rides along on every window because the importer reads the account's
# user list out of the same response to put names to the log's user_ids.
FULL = """query ($b: [ID!], $t: ISO8601DateTime) {
  users { id name email }
  boards(ids: $b) {
    id
    activity_logs(limit: 10000, page: 1, to: $t) { id event data user_id created_at }
  }
}"""


def ask(tok, query, variables, tries=3):
    for n in range(tries):
        try:
            body = json.dumps({"query": query, "variables": variables}).encode()
            # No API-Version header: an older pinned version rejects fields this
            # export needs, and the account default has always been right here.
            req = urllib.request.Request(
                "https://api.monday.com/v2", data=body,
                headers={"Content-Type": "application/json", "Authorization": tok})
            with urllib.request.urlopen(req, timeout=600) as f:
                answer = json.loads(f.read())
            if answer.get("errors"):
                raise RuntimeError(json.dumps(answer["errors"], ensure_ascii=False)[:400])
            return answer
        except Exception as err:                       # noqa: BLE001 - retried
            if n == tries - 1:
                raise
            print(f"   ! {str(err)[:140]} — ניסיון חוזר בעוד 15 שניות")
            time.sleep(15)


def when(raw):
    """monday stamps a log in ten-millionths of a second since the epoch."""
    return dt.datetime.utcfromtimestamp(int(raw) / 1e7).replace(microsecond=0)


def walk(tok, board, heavy):
    """Every log row the board has, newest window first."""
    seen, pages, to, windows = set(), [], None, 0
    while windows < MAX_WINDOWS:
        windows += 1
        answer = ask(tok, FULL if heavy else LIGHT,
                     {"b": [board],
                      "t": to.strftime("%Y-%m-%dT%H:%M:%SZ") if to else None})
        boards = answer["data"]["boards"]
        logs = boards[0]["activity_logs"] if boards else []
        fresh = [row for row in logs if row["id"] not in seen]
        seen.update(row["id"] for row in fresh)
        oldest = when(logs[-1]["created_at"]) if logs else None
        span = f"{oldest} .. {when(logs[0]['created_at'])}" if logs else "—"
        print(f"חלון {windows}: {len(logs)} רשומות ({len(fresh)} חדשות)   {span}")
        if heavy and fresh:
            # only the new rows are kept, so the merged file holds each log once
            boards[0]["activity_logs"] = fresh
            pages.append(answer)
        if len(logs) < CEILING or oldest is None:
            break
        if to is not None and oldest >= to:
            # the window did not move: more than 10,000 rows share one second,
            # and no `to` can get behind them. Stopping beats looping.
            print("   ! החלון לא זז — יותר מ-10,000 רשומות באותה שנייה. עוצר כאן")
            break
        to = oldest
    return seen, pages, windows


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("שימוש: python3 scripts/monday_history.py <boardId> [--count]")
    board, heavy = args[0], "--count" not in sys.argv
    seen, pages, windows = walk(token(), board, heavy)
    print(f"\nסה\"כ {len(seen)} רשומות היסטוריה ב-{windows} חלונות")
    if not heavy:
        return
    tail = board[-3:]
    for i, answer in enumerate(pages, 1):
        path = os.path.join(OUT, f"response{tail}h{i}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(answer, f, ensure_ascii=False, separators=(",", ":"))
        print(f"   ✓ {path}  {os.path.getsize(path) / 1048576:.1f}MB")


if __name__ == "__main__":
    main()
