#!/usr/bin/env bash
set -u
APP=/home/erez/.openclaw/workspace/cityos
cd "$APP/backend" || exit 1

echo "=== stop existing server on :8000 ==="
PID=$(ss -ltnp 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
if [ -n "${PID:-}" ]; then kill "$PID" 2>/dev/null; sleep 2; echo "killed $PID"; else echo "(none)"; fi

echo "=== start server (detached) from cityos venv ==="
source "$APP/venv/bin/activate" 2>/dev/null || true
set -a; [ -f "$APP/.env" ] && . "$APP/.env"; set +a   # load DEEPSEEK_API_KEY
pip show python-dotenv >/dev/null 2>&1 || pip install -q python-dotenv 2>/dev/null || true
setsid nohup python main.py > "$APP/server.log" 2>&1 < /dev/null &
sleep 4

echo "=== verify ==="
echo -n "status: ";   curl -sS -m 8 http://localhost:8000/api/status
echo; echo -n "boards: "; curl -sS -m 8 http://localhost:8000/api/boards | head -c 200
echo; echo -n "dashboard: "; curl -sS -m 8 http://localhost:8000/api/dashboard | head -c 200
echo; echo "homepage title line:"; curl -sS -m 8 http://localhost:8000/ | grep -o '<title>[^<]*</title>'
echo "uses monday css? "; curl -sS -m 8 http://localhost:8000/ | grep -c 'Vibe inspired'
echo "=== server.log tail ==="; tail -6 "$APP/server.log"
