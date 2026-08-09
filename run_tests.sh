#!/usr/bin/env bash
# CityOS pre-deploy gate — regression tests + security scan.
# Uses an isolated temp DB; never touches backend/cityos.db.
# Set SKIP_SECURITY_GATE=1 to run only the tests.
set -e
cd "$(dirname "$0")"
chmod +x scripts/security_gate.sh 2>/dev/null || true

./venv/bin/python -m pytest "$@"

if [ "${SKIP_SECURITY_GATE:-0}" != "1" ]; then
  echo
  ./scripts/security_gate.sh
fi
