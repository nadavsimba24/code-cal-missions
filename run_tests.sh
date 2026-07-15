#!/usr/bin/env bash
# CityOS regression suite — run before every version bump.
# Uses an isolated temp DB; never touches backend/cityos.db.
set -e
cd "$(dirname "$0")"
exec ./venv/bin/python -m pytest "$@"
