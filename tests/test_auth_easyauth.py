"""מצב easyauth — הזהות מגיעה מ-Entra בלבד.

This is the mode a real deployment runs in: the platform terminates the login
and injects X-MS-CLIENT-PRINCIPAL*. Nothing the client sends may stand in for
it — no picker, no header, no cookie — and an unknown identity is refused
rather than let in. These are the guarantees the switch to Azure depends on.
"""
import base64
import json

import pytest

import auth as cityos_auth
import main as cityos_main


@pytest.fixture
def easyauth(monkeypatch):
    # main imported the name directly, so both bindings have to be patched
    monkeypatch.setattr(cityos_auth, "auth_mode", lambda: "easyauth")
    monkeypatch.setattr(cityos_main, "auth_mode", lambda: "easyauth")


def _email(uid):
    """Straight from the database — by the time this runs the mode is already
    easyauth, so an API call would be refused."""
    from models import User
    from sqlalchemy.orm import Session
    with Session(cityos_main.engine) as db:
        return db.query(User).filter(User.id == uid).first().email


def _principal(email, name="משתמש"):
    blob = {"claims": [{"typ": "preferred_username", "val": email},
                       {"typ": "name", "val": name}]}
    return base64.b64encode(json.dumps(blob).encode()).decode()


def _users(client, **kw):
    return client.get("/api/boards", headers={"X-CityOS-User": ""}, **kw)


@pytest.fixture
def admin_email(admin_id):
    return _email(admin_id)


def test_entra_identity_is_accepted(client, easyauth, admin_id, admin_email):
    r = client.get("/api/auth/me", headers={"X-CityOS-User": "",
                                            "X-MS-CLIENT-PRINCIPAL": _principal(admin_email)})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == admin_id


def test_the_flattened_header_also_works(client, easyauth, admin_id, admin_email):
    r = client.get("/api/auth/me", headers={"X-CityOS-User": "",
                                            "X-MS-CLIENT-PRINCIPAL-NAME": admin_email})
    assert r.status_code == 200 and r.json()["id"] == admin_id


def test_no_identity_is_refused(client, easyauth):
    assert _users(client).status_code == 401


def test_the_dev_header_cannot_stand_in_for_entra(client, easyauth, admin_id):
    """The picker's header must carry no weight once a real IdP is in front."""
    r = client.get("/api/boards", headers={"X-CityOS-User": str(admin_id)})
    assert r.status_code == 401


def test_the_dev_cookie_cannot_stand_in_either(client, easyauth, admin_id):
    r = client.get("/api/boards", headers={"X-CityOS-User": ""},
                   cookies={"cityos_user": str(admin_id)})
    assert r.status_code == 401


def test_an_identity_with_no_account_is_refused(client, easyauth):
    r = client.get("/api/boards", headers={"X-CityOS-User": "",
                                           "X-MS-CLIENT-PRINCIPAL": _principal("stranger@example.com")})
    assert r.status_code in (401, 403)


def test_a_malformed_principal_is_refused(client, easyauth):
    r = client.get("/api/boards", headers={"X-CityOS-User": "",
                                           "X-MS-CLIENT-PRINCIPAL": "not-base64!!"})
    assert r.status_code == 401


def test_the_status_endpoint_reports_the_mode(client, easyauth):
    """The SPA shows the picker only when the server says it is in dev."""
    assert client.get("/api/status").json()["auth_mode"] == "easyauth"
