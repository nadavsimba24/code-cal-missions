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
# Identity now comes from the transport, never from a request parameter. The
# suite runs in dev mode, where the X-CityOS-User header carries it.
os.environ["CITYOS_AUTH_MODE"] = "dev"

import pytest  # noqa: E402
from fastapi.testclient import TestClient as _RawTestClient  # noqa: E402
import main as cityos_main  # noqa: E402  (imports trigger seeding into the temp DB)


class TestClient(_RawTestClient):
    """A client that signs each request as the user the test names.

    The suite has always expressed "who is acting" with an actor_id/user_id
    parameter. The server no longer reads those — it reads the authenticated
    identity — so this promotes the parameter into the auth header, keeping every
    existing test meaningful while exercising the real auth path. Tests that the
    parameters are *not* trusted set the header explicitly (see test_authz.py).

    Requests that name no actor are signed as the workspace admin — the suite is
    mostly about behaviour, not about who may do it. To exercise the anonymous
    case, pass the header explicitly as empty: headers={"X-CityOS-User": ""}.
    """

    def request(self, method, url, **kw):
        # The picker's identity is honoured only for a locally served app, and
        # the suite stands in for exactly that. TestClient would otherwise send
        # host: testserver, which is (rightly) treated as remote. A test that
        # wants the remote behaviour passes its own host header.
        if "host" not in {k.lower() for k in (kw.get("headers") or {})}:
            kw["headers"] = {**(kw.get("headers") or {}), "host": "localhost"}
        if "x-cityos-user" not in {k.lower() for k in (kw.get("headers") or {})}:
            actor = _actor_from(url, kw.get("json"))
            if actor is None:
                actor = ADMIN_ID
            kw["headers"] = {**(kw.get("headers") or {}), "X-CityOS-User": str(actor)}
        return super().request(method, url, **kw)


def _actor_from(url, body):
    """actor_id wins over user_id — where both appear, user_id is the target."""
    import urllib.parse
    if isinstance(body, dict):
        for key in ("actor_id", "user_id"):
            if body.get(key) is not None:
                return body[key]
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(str(url)).query)
    for key in ("actor_id", "user_id"):
        if qs.get(key):
            return qs[key][0]
    return None

# The demo-user purge (main._purge_removed_demo_users) deletes the original seed
# members that this suite used to hardcode (ids 4/5). To stay seed-independent we
# create stable, non-admin test users via the API and enroll them in board 1.
ADMIN_ID = 1     # משה — workspace admin, survives the purge
_boot = TestClient(cityos_main.app)


_AS_ADMIN = {"X-CityOS-User": str(ADMIN_ID)}


def _ensure_user(name, email):
    for u in _boot.get("/api/users", headers=_AS_ADMIN).json():
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
