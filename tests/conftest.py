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

# The suite must not send mail. Inviting somebody to a board is an ordinary
# thing for a test to do, and _send_email is real: with a provider key in the
# developer's own .env, every run delivered actual invitations to whatever
# EMAIL_DEV_REDIRECT points at — until the provider's daily quota answered 429
# and started failing sends for real work too. No key means _send_email logs and
# drops, which is what a test wants; a test that cares about the mail asserts on
# it by replacing the sender (see test_invite_tells_the_invitee.py).
# Set empty rather than removed: main.py calls load_dotenv(), which fills in any
# key that is ABSENT from the environment — deleting these just handed the
# developer's .env a second chance to supply them. An empty value is present, so
# dotenv leaves it alone, and every reader treats it as "not configured".
for _k in ("SENDGRID_API_KEY", "RESEND_API_KEY", "EMAIL_DEV_REDIRECT", "MAIL_PROVIDER"):
    os.environ[_k] = ""

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


def _primary_env_id():
    for e in _boot.get("/api/environments", headers=_AS_ADMIN).json()["environments"]:
        if e.get("is_primary"):
            return e["id"]
    return None


# A board invitation only reaches somebody who is already in the board's
# environment, and the primary workspace is no longer everybody's by
# definition — a user created today is in no environment until an admin puts
# them in one. So these two are enrolled the way a real admin enrolls anybody:
# the workspace first, then the board inside it.
PRIMARY_ENV_ID = _primary_env_id()
for _uid in (MEMBER_ID, GUINEA_ID):
    if PRIMARY_ENV_ID:
        _boot.post(f"/api/environments/{PRIMARY_ENV_ID}/members",
                   json={"actor_id": ADMIN_ID, "user_id": _uid, "role": "member"})
    _boot.post("/api/boards/1/members", json={"actor_id": ADMIN_ID, "user_id": _uid, "role": "editor"})


def join_primary_env(client, uid, role="member"):
    """Put a user in the primary workspace, the way the admin screen does.

    Creating a user makes them a member of nothing: the primary workspace
    stopped being everybody's by definition, so a test that invites a freshly
    created person to a board in it has to enroll them first — the board
    invitation is refused otherwise (see _outside_board_env)."""
    if PRIMARY_ENV_ID:
        client.post(f"/api/environments/{PRIMARY_ENV_ID}/members",
                    json={"actor_id": ADMIN_ID, "user_id": uid, "role": role})


@pytest.fixture(scope="session")
def client():
    with TestClient(cityos_main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Every test starts with empty rate-limit counters.

    The whole suite is one client address ("testclient"), so the limiter's
    budgets — sized for one person or one office — were spent by the tests
    BEFORE the one that ran out: test_form_submission.py met 429s nine tests
    in, on sends that were each perfectly ordinary. The limiter is tested on
    its own, deliberately, in test_a_stranger_is_slowed_down.py; everywhere
    else a 429 would be a test reading its neighbours' traffic."""
    cityos_main._rl_hits.clear()
    cityos_main._form_hits.clear()
    yield


@pytest.fixture
def admin_id():
    return ADMIN_ID


@pytest.fixture
def member_id():
    return MEMBER_ID


@pytest.fixture
def guinea_id():
    return GUINEA_ID
