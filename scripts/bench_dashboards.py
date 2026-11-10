#!/usr/bin/env python3
"""מדידת עומס לדשבורדים — מספרים בפועל מול יעד DASH-28.2.

The target the spec sets is explicit and is a target for MEASUREMENT, not a
promise: "השלמת 95% מהבקשות בתוך 3 שניות, מול 10,000 רשומות בסך הכול,
10 ווידג׳טים ו־20 צופים במקביל" — and DASH-28.3 adds that exceeding it does
not license showing a partial total as though it were a full one.

So this builds exactly that shape, runs it, and prints what happened. It
asserts nothing; it reports. Run it, read the p95, and compare two versions
of the code against each other — that is what makes a number mean something.

The population deliberately includes the two expensive sources: a formula
column (evaluated per record, in Python) and a multi-valued mirror reading
another board through a connect column. DASH-28.2 names both — "לאמת את
המגבלות בבדיקות עומס, כולל נוסחאות ומראה" — because they are where the cost
is, and a load test over plain number columns would measure the easy half.

    ./venv/bin/python scripts/bench_dashboards.py [--records N] [--viewers N]
"""
import argparse
import os
import pathlib
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# A database of its own, built here and thrown away. Never the real one.
_TMP = tempfile.mkdtemp(prefix="dash-bench-")
os.environ["CITYOS_DB_PATH"] = os.path.join(_TMP, "bench.db")
os.environ["CITYOS_UPLOAD_DIR"] = os.path.join(_TMP, "uploads")
os.environ["CITYOS_AUTH_MODE"] = "dev"
for _k in ("SENDGRID_API_KEY", "RESEND_API_KEY", "EMAIL_DEV_REDIRECT", "MAIL_PROVIDER"):
    os.environ[_k] = ""

import main as m                                    # noqa: E402
from fastapi.testclient import TestClient           # noqa: E402
from sqlalchemy.orm import Session                  # noqa: E402
from models import Board, Task, Group, User         # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--records", type=int, default=10000)
ap.add_argument("--viewers", type=int, default=20)
ap.add_argument("--widgets", type=int, default=10)
A = ap.parse_args()

ADMIN = 1
c = TestClient(m.app, headers={"host": "localhost", "X-CityOS-User": str(ADMIN)})


def say(s=""):
    print(s, flush=True)


say(f"בונה אוכלוסייה: {A.records} רשומות · {A.widgets} ווידג׳טים · {A.viewers} צופים")
t0 = time.perf_counter()

near = c.post("/api/boards", json={"name": "עומס ראשי", "user_id": ADMIN}).json()["id"]
far = c.post("/api/boards", json={"name": "עומס מקושר", "user_id": ADMIN}).json()["id"]


def cols(b):
    return c.get(f"/api/boards/{b}").json()["columns"]


def add_col(b, col):
    c.patch(f"/api/boards/{b}", json={"actor_id": ADMIN, "columns": cols(b) + [col]})
    return cols(b)[-1]


far_num = add_col(far, {"type": "number", "title": "ערך רחוק"})
num = add_col(near, {"type": "number", "title": "תקציב", "number": {"unit": "₪"}})
calc = add_col(near, {"type": "formula", "title": "כפול", "formula": "{תקציב}*2"})
conn = add_col(near, {"type": "connect", "title": "קישור",
                      "connect": {"board_ids": [far], "multiple": True, "two_way": False}})
mirror = add_col(near, {"type": "mirror", "title": "מראה",
                        "mirror_of": {"connect": conn["id"], "field": far_num["id"]}})
dcol = add_col(near, {"type": "date", "title": "מועד"})

# Written straight through the ORM: this is building a fixture, not measuring
# the write path, and 10,000 POSTs would dominate the clock for no answer.
STATUSES = ["done", "in_progress", "on_hold", "todo", "review"]
with Session(m.engine) as db:
    groups = []
    for i in range(8):
        g = Group(board_id=near, name=f"קבוצה {i}", position=i)
        db.add(g)
        groups.append(g)
    db.flush()
    far_ids = []
    for i in range(200):
        t = Task(board_id=far, title=f"רחוק {i}", position=i,
                 custom_fields={far_num["id"]: (i % 50) + 1})
        db.add(t)
        far_ids.append(t)
    db.flush()
    far_ids = [t.id for t in far_ids]
    users = db.query(User).limit(5).all()
    n_far = len(far_ids)
    for i in range(A.records):
        cf = {dcol["id"]: f"2026-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"}
        # a tenth of the records carry no number — the blanks R03/R04 are about
        if i % 10:
            cf[num["id"]] = (i % 97) - 10        # includes negatives
        # a twentieth link to three far records — the mirror's cost
        if i % 20 == 0:
            cf[conn["id"]] = [far_ids[i % n_far], far_ids[(i + 1) % n_far],
                              far_ids[(i + 2) % n_far]]
        t = Task(board_id=near, title=f"רשומה {i}", position=i,
                 group_id=groups[i % len(groups)].id,
                 status=STATUSES[i % len(STATUSES)], custom_fields=cf)
        if i % 7 == 0 and users:
            t.assignees = [users[i % len(users)], users[(i + 1) % len(users)]]
        db.add(t)
        if i % 1000 == 999:
            db.flush()
    db.commit()
say(f"  נבנה ב־{time.perf_counter() - t0:.1f} שניות")

env = next(e["id"] for e in c.get("/api/environments").json()["environments"]
           if e.get("is_primary"))
d = c.post("/api/dashboards",
           json={"environment_id": env, "name": "עומס",
                 "sources": [{"board_id": near, "groups": None}]}).json()
ver = d["config_version"]
mapping = {str(near): {"amount": num["id"], "calcd": calc["id"],
                       "mir": mirror["id"], "__date__": dcol["id"]}}

# Ten widgets across every source and every shape the spec names.
SHAPES = [
    ("numbers", "ספירה", {"metrics": [{"key": "m", "calc": "count"}]}),
    ("numbers", "סכום מספר", {"mapping": mapping,
                              "metrics": [{"key": "m", "field": "amount", "calc": "sum"}]}),
    ("numbers", "ממוצע מספר", {"mapping": mapping,
                               "metrics": [{"key": "m", "field": "amount", "calc": "avg"}]}),
    ("numbers", "סכום נוסחה", {"mapping": mapping,
                               "metrics": [{"key": "m", "field": "calcd", "calc": "sum"}]}),
    ("numbers", "סכום מראה", {"mapping": mapping,
                              "metrics": [{"key": "m", "field": "mir", "calc": "sum"}]}),
    ("chart", "עמודות לפי סטטוס", {"metrics": [{"key": "m", "calc": "count"}],
                                   "chart": {"type": "vbar", "dimension": "status"}}),
    ("chart", "אופקי לפי קבוצה", {"mapping": mapping,
                                  "metrics": [{"key": "m", "field": "amount", "calc": "sum"}],
                                  "chart": {"type": "hbar", "dimension": "group"}}),
    ("chart", "עוגה לפי סטטוס", {"metrics": [{"key": "m", "calc": "count"}],
                                 "chart": {"type": "pie", "dimension": "status"}}),
    ("chart", "מוערם סטטוס×קבוצה", {"metrics": [{"key": "m", "calc": "count"}],
                                    "chart": {"type": "stacked", "dimension": "status",
                                              "split": "group"}}),
    ("chart", "קו לפי חודש", {"mapping": mapping,
                              "metrics": [{"key": "m", "field": "amount", "calc": "sum"}],
                              "chart": {"type": "line", "dimension": "date",
                                        "period": "month"}}),
]
widgets = []
for kind, title, extra in SHAPES[:A.widgets]:
    r = c.post(f"/api/dashboards/{d['id']}/widgets",
               json={"config_version": ver, "type": kind, "title": title, **extra})
    if r.status_code != 200:
        say(f"  ⚠️  {title}: {r.status_code} {r.text[:120]}")
        continue
    ver = r.json()["config_version"]
    widgets.append((kind, title, r.json()["widget"]["id"]))
say(f"  {len(widgets)} ווידג׳טים נוצרו")

# Twenty readers, each asking for every widget — the shape DASH-28.2 names.
viewers = [ADMIN] * A.viewers


def one(args):
    """One viewer asking for one widget.

    The client is SHARED on purpose. Building a TestClient per call spins up
    an event loop and a blocking portal each time, which costs far more than
    the request and makes the measurement a measurement of the harness — the
    first run of this script reported a p95 of 48s for work that takes 0.13s
    single-threaded, and all of the difference was here.
    """
    kind, title, wid = args
    path = "chart" if kind == "chart" else "compute"
    t = time.perf_counter()
    r = c.post(f"/api/dashboards/{d['id']}/widgets/{wid}/{path}", json={})
    dt = time.perf_counter() - t
    body = r.json() if r.status_code == 200 else {}
    return (title, dt, r.status_code, body.get("state"))


# ── a serial pass first ──
# Latency under load is two different costs added together — what one request
# costs, and what the contention costs — and a single number cannot be told
# apart into them. So each widget is timed alone, warm, before anybody else
# is asking: if THIS is already over the target the work is too slow, and if
# it is not, the gap is concurrency and the fix is a different one.
say("\nמדידה סדרתית (בקשה אחת בכל רגע)…")
for kind, title, wid in widgets:
    path = "chart" if kind == "chart" else "compute"
    c.post(f"/api/dashboards/{d['id']}/widgets/{wid}/{path}", json={})      # warm
    t = time.perf_counter()
    r = c.post(f"/api/dashboards/{d['id']}/widgets/{wid}/{path}", json={})
    say(f"  {time.perf_counter() - t:6.3f}s   {title}  [{r.json().get('state')}]")

# ── and now against a real server ──
# TestClient drives the app through a single blocking portal and one event
# loop, so twenty threads inside it queue on the harness and not on the work:
# it reported a p95 of 46s for a request that costs 0.2s warm. A number about
# concurrency has to come from something that is actually concurrent, so the
# app is started under uvicorn and hit over HTTP.
import json as _json
import subprocess
import urllib.request

PORT = int(os.getenv("BENCH_PORT", "8777"))
say(f"\nמפעיל שרת אמיתי על פורט {PORT}…")
srv = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
     "--port", str(PORT), "--log-level", "error"],
    cwd=str(ROOT / "backend"),
    env={**os.environ, "PYTHONPATH": str(ROOT / "backend")},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ping():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=1).read()
        return True
    except Exception:
        return False


for _ in range(100):
    if ping():
        break
    time.sleep(0.2)
else:
    srv.kill()
    say("❌ השרת לא עלה")
    sys.exit(1)


def hit(path, body=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=_json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json", "X-CityOS-User": str(ADMIN),
                 "Host": "localhost"})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = _json.loads(r.read())
        return time.perf_counter() - t, 200, out
    except Exception as e:                                   # noqa: BLE001
        return time.perf_counter() - t, 0, {"error": str(e)[:80]}


try:
    say("\nמדידה סדרתית מול השרת…")
    hit(f"/api/dashboards/{d['id']}/compute")                # warm
    dt, _s, out = hit(f"/api/dashboards/{d['id']}/compute")
    say(f"  {dt:6.3f}s   דשבורד שלם ({len(out.get('widgets', []))} ווידג׳טים, בקשה אחת)")
    for kind, title, wid in widgets[:3]:
        path = "chart" if kind == "chart" else "compute"
        hit(f"/api/dashboards/{d['id']}/widgets/{wid}/{path}")
        dt, _s, _o = hit(f"/api/dashboards/{d['id']}/widgets/{wid}/{path}")
        say(f"  {dt:6.3f}s   {title} (ווידג׳ט בודד)")

    def open_dash(_i):
        dt, code, body = hit(f"/api/dashboards/{d['id']}/compute")
        states = {x.get("state") for x in body.get("widgets", [])}
        return dt, code, ("ok" if states and states <= {"ok", "no_data"} else str(states or body))

    say(f"\n{A.viewers} צופים פותחים את הדשבורד במקביל…")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=A.viewers) as ex:
        res = list(ex.map(open_dash, range(A.viewers)))
    wall = time.perf_counter() - t0
    ts = sorted(dt for dt, _c, _s in res)
    p95 = ts[min(len(ts) - 1, int(len(ts) * 0.95))]
    bad = [(c, s) for _dt, c, s in res if c != 200 or s != "ok"]
    say(f"\n── תוצאות בפועל ──")
    say(f"רשומות: {A.records} · ווידג׳טים: {len(widgets)} · צופים: {A.viewers}")
    say(f"זמן קיר: {wall:.1f}s · חציון: {statistics.median(ts):.3f}s · "
        f"p95: {p95:.3f}s · מקסימום: {ts[-1]:.3f}s")
    say(f"יעד DASH-28.2 (p95 ≤ 3s): {'✅ עומד' if p95 <= 3 else '❌ חורג'}")
    if bad:
        say(f"⚠️  {len(bad)} בקשות לא תקינות: {bad[:3]}")
    else:
        say("כל הבקשות הסתיימו תקין — אין תוצאה חלקית ואין מדד שגוי.")
finally:
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except Exception:                                        # noqa: BLE001
        srv.kill()
