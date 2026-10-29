#!/usr/bin/env bash
set -u
APP="$(cd "$(dirname "$0")" && pwd)"
cd "$APP/backend" || exit 1

echo "=== stop existing server on :8000 ==="
# -sTCP:LISTEN, and every match rather than the first.
#
# 2026-10-29: this said `lsof -ti tcp:8000 | head -1`. That list is not only
# the listener — anything holding a socket to the port is in it — and taking
# the first of it killed a process that was not the server. The real listener
# survived, the replacement could not bind and died on the spot, and the
# script went on to print a cheerful "killed <pid>" and a passing status
# check answered by the OLD process. A backend change then looked like it had
# no effect, which is a very expensive way to lose an hour.
PIDS=$(lsof -ti tcp:8000 -sTCP:LISTEN 2>/dev/null)
if [ -n "${PIDS:-}" ]; then
  echo "$PIDS" | xargs kill 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -z "$(lsof -ti tcp:8000 -sTCP:LISTEN 2>/dev/null)" ] && break
    sleep 1
  done
  echo "killed: $(echo $PIDS)"
else
  echo "(none)"
fi
if [ -n "$(lsof -ti tcp:8000 -sTCP:LISTEN 2>/dev/null)" ]; then
  echo "!! :8000 is still held — refusing to start a second server that cannot bind."
  echo "   holder: $(lsof -ti tcp:8000 -sTCP:LISTEN | tr '\n' ' ')"
  exit 1
fi

echo "=== start server (detached) from current project venv ==="
source "$APP/venv/bin/activate" 2>/dev/null || true
set -a; [ -f "$APP/.env" ] && . "$APP/.env"; set +a   # load DEEPSEEK_API_KEY
pip show python-dotenv >/dev/null 2>&1 || pip install -q python-dotenv 2>/dev/null || true
nohup python main.py > "$APP/server.log" 2>&1 < /dev/null &
NEW=$!
sleep 4
# A server that died on startup used to be indistinguishable from one that
# came up, because the checks below are answered by whoever holds the port.
if ! kill -0 "$NEW" 2>/dev/null; then
  echo "!! the server exited during startup — last lines of server.log:"
  tail -20 "$APP/server.log"
  exit 1
fi
echo "started pid $NEW"

echo "=== verify ==="
echo -n "status: ";   curl -sS -m 8 http://localhost:8000/api/status
echo; echo -n "users: "; curl -sS -m 8 http://localhost:8000/api/users
echo; echo -n "boards: "; curl -sS -m 8 http://localhost:8000/api/boards | head -c 200
echo; echo -n "dashboard: "; curl -sS -m 8 http://localhost:8000/api/dashboard | head -c 200
echo; echo "homepage title line:"; curl -sS -m 8 http://localhost:8000/ | grep -o '<title>[^<]*</title>'
echo "uses monday css? "; curl -sS -m 8 http://localhost:8000/ | grep -c 'Vibe inspired'
echo "=== server.log tail ==="; tail -6 "$APP/server.log"
