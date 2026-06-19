import os, json, time, subprocess, urllib.request, urllib.error

APP = "/home/erez/.openclaw/workspace/cityos"
BASE = "http://localhost:8000"
def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()

print("="*60); print(" CODE-CAL MISSIONS — health & sync check"); print("="*60)

# 1) running server + freshness
pid = sh("ss -ltnp 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2")
print("\n[1] שרת רץ על :8000  pid=", pid or "NONE")
srv_start = 0
if pid:
    started = sh(f"ps -o lstart= -p {pid}")
    srv_start = float(sh(f"stat -c %Y /proc/{pid} 2>/dev/null") or 0)
    print("    הופעל:", started)

files = ["backend/main.py","backend/models.py","backend/bim_bridge.py","backend/seed.py",
         "backend/import_board.py","frontend/index.html",".env","run.sh"]
print("\n[2] קבצים (mtime):")
newest = 0
for f in files:
    p = os.path.join(APP,f)
    if os.path.exists(p):
        m = os.path.getmtime(p); newest=max(newest,m)
        print(f"    {time.strftime('%m-%d %H:%M',time.localtime(m))}  {f}")
    else:
        print(f"    MISSING        {f}")
if srv_start:
    stale = newest > srv_start
    print(f"\n    => {'⚠️ הקוד בדיסק חדש מהשרת הרץ (צריך restart)' if stale else '✓ השרת מסונכרן עם הדיסק'}")

# 3) OpenClaw recent activity (possible overwrites)
print("\n[3] שינויים ב-30 הדקות האחרונות (פעילות OpenClaw?):")
recent = sh(f"find {APP}/backend {APP}/frontend -type f \\( -name '*.py' -o -name '*.html' \\) -mmin -30 -not -path '*/__pycache__/*'")
print("    " + (recent.replace(APP+"/","").replace("\n","\n    ") if recent else "(אין — אף קובץ לא שונה לאחרונה)"))

# 4) my-changes survived? (detect OpenClaw clobber)
print("\n[4] השינויים שלי שרדו בדיסק:")
def has(path, needle):
    try: return needle in open(os.path.join(APP,path),encoding='utf-8').read()
    except: return False
checks = [
    ("backend/main.py","CODE-CAL MISSIONS"), ("backend/main.py","/api/ai/models"),
    ("backend/main.py","/api/ai/train"), ("backend/main.py","deepseek"),
    ("frontend/index.html","CODE-CAL MISSIONS"), ("frontend/index.html","Figtree"),
    ("frontend/index.html","Rubik"), ("frontend/index.html",'id="term"'),
    ("frontend/index.html","Term.open"), ("frontend/index.html","statusPill"),
]
for path,needle in checks:
    print(f"    {'✓' if has(path,needle) else '✗ נדרס/חסר!':12} {path}: {needle}")

# 5) API sweep
print("\n[5] בדיקת endpoints:")
def get(p):
    try:
        r=urllib.request.urlopen(BASE+p,timeout=15); return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:80]
    except Exception as e: return "ERR", str(e)[:80]
eps = ["/api/status","/api/dashboard","/api/boards","/api/boards/1","/api/boards/8",
       "/api/tasks","/api/citizen-requests","/api/permits","/api/users","/api/departments",
       "/api/transport/stops","/api/infrastructure/assets","/api/swarm/agents",
       "/api/forms/templates","/api/viz/board-insights","/api/viz/timeline",
       "/api/graph/context","/api/ai/models","/api/bim/bcf-topics"]
ok=0
for e in eps:
    code,body = get(e)
    n=""
    try:
        d=json.loads(body)
        if isinstance(d,list): n=f"{len(d)} items"
        elif isinstance(d,dict): n=",".join(list(d.keys())[:4])
    except: n=str(body)[:40]
    flag = "✓" if code==200 else "✗"
    if code==200: ok+=1
    print(f"    {flag} {str(code):4} {e:34} {n}")
print(f"    => {ok}/{len(eps)} OK")

# 6) frontend served = disk?
print("\n[6] frontend מוגש:")
_,html = get("/")
for s in ["CODE-CAL MISSIONS","Figtree",'id="term"',"deepseek"]:
    print(f"    {'✓' if s in html else '✗'} {s}")
print(f"    'CityOS' שאריות: {html.count('CityOS')}")

# 7) DeepSeek agent live
print("\n[7] סוכן DeepSeek (קריאה חיה):")
try:
    req=urllib.request.Request(BASE+"/api/ai/query",data=json.dumps({"prompt":"ענה במילה אחת: 2+2=?","context":"בדיקה","model":"deepseek-chat"}).encode(),headers={'Content-Type':'application/json'})
    d=json.loads(urllib.request.urlopen(req,timeout=70).read())
    print(f"    success={d.get('success')} provider={d.get('provider')} model={d.get('model')}")
    print(f"    תשובה: {(d.get('response') or '')[:120]}")
except Exception as e:
    print("    ERR", str(e)[:120])
print("\n"+"="*60)
