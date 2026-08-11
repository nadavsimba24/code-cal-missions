#!/usr/bin/env bash
set -euo pipefail

APP="/Users/mashcal/Downloads/code-cal-missions"
cd "$APP/backend"
exec "$APP/venv/bin/python" main.py
