#!/usr/bin/env bash
# ── Security gate (CI / pre-deploy) ──────────────────────────────────
# Fails the build on any HIGH-severity finding from the deterministic, offline
# scanners (SAST + secrets). The authz heuristic is advisory (MEDIUM) and is
# surfaced but never blocks. Run dependency CVEs separately (needs network):
#   ./venv/bin/python scripts/security_agent.py scan --only deps
set -u
cd "$(dirname "$0")/.."
PY=./venv/bin/python

echo "── שער אבטחה: SAST + סודות ──"
"$PY" scripts/security_agent.py scan --only sast,secrets
HIGH=$?

# advisory: count of endpoints with no visible permission check (never blocks)
AUTHZ=$("$PY" scripts/security_agent.py scan --only authz --json 2>/dev/null \
        | "$PY" -c "import sys,json;print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
echo "ℹ️  authz (מייעץ, לא חוסם): $AUTHZ endpoints ללא בדיקת הרשאה נראית"

if [ "${HIGH:-0}" -gt 0 ]; then
  echo "❌ שער האבטחה נכשל — ${HIGH} ממצא(י) חומרה גבוהה. תקני לפני דיפלוי."
  exit 1
fi
echo "✅ שער האבטחה עבר — אין ממצאי חומרה גבוהה."
