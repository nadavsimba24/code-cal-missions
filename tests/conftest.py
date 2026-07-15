"""Shared pytest fixtures for the CityOS regression suite.

The app seeds its database at import time, so we point it at an isolated
temporary SQLite file *before* importing `main`. Your real backend/cityos.db
is never touched.
"""
import os
import sys
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

# Isolated DB + upload dir — MUST be set before importing the app.
_TMP = tempfile.mkdtemp(prefix="cityos-test-")
os.environ["CITYOS_DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["CITYOS_UPLOAD_DIR"] = os.path.join(_TMP, "uploads")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main as cityos_main  # noqa: E402  (imports trigger seeding into the temp DB)

# Seeded identities (see backend/seed.py + main._seed_memberships):
#   users 1-3 are workspace admins; users 4-7 are plain members.
ADMIN_ID = 1     # workspace admin
MEMBER_ID = 4    # workspace member (non-admin)
GUINEA_ID = 5    # a member we mutate in tests, then restore


@pytest.fixture(scope="session")
def client():
    with TestClient(cityos_main.app) as c:
        yield c


@pytest.fixture
def admin_id():
    return ADMIN_ID


@pytest.fixture
def member_id():
    return MEMBER_ID


@pytest.fixture
def guinea_id():
    return GUINEA_ID
