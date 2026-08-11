"""Vercel serverless entrypoint for the CityOS FastAPI app.

Vercel's filesystem is read-only except for /tmp, so we point the SQLite DB
and upload dir there. The DB is re-seeded on each cold start (demo mode —
data does not persist across cold starts).
"""
import os
import sys

# Writable locations on Vercel's serverless filesystem.
os.environ.setdefault("CITYOS_DB_PATH", "/tmp/cityos.db")
os.environ.setdefault("CITYOS_UPLOAD_DIR", "/tmp/uploads")

# Make the backend package importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from main import app  # noqa: E402  (FastAPI ASGI app picked up by @vercel/python)
