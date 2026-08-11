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

# The demo-user purge (main._purge_removed_demo_users) deletes the original seed
# members that this suite used to hardcode (ids 4/5). To stay seed-independent we
# create stable, non-admin test users via the API and enroll them in board 1.
ADMIN_ID = 1     # משה — workspace admin, survives the purge
_boot = TestClient(cityos_main.app)


def _ensure_user(name, email):
    for u in _boot.get("/api/users").json():
        if u.get("email") == email:
            return u["id"]
    r = _boot.post("/api/users", json={"actor_id": ADMIN_ID, "name": name, "email": email, "role": "member"})
    return r.json()["id"]


MEMBER_ID = _ensure_user("בודק חבר", "test.member@cityos.test")     # non-admin board-1 member
GUINEA_ID = _ensure_user("בודק ניסוי", "test.guinea@cityos.test")  # a member we mutate in tests
for _uid in (MEMBER_ID, GUINEA_ID):
    _boot.post("/api/boards/1/members", json={"actor_id": ADMIN_ID, "user_id": _uid, "role": "editor"})


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
