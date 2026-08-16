"""Group 24 — in-app Entra ID SSO (backend/entra.py).

The point of these is that the *checks* are real. A sign-in module that happily
accepts an unsigned token, a replayed one, or a login someone else started is
worse than no SSO at all, because it looks like security. Each test below
removes exactly one of those guarantees and asserts we refuse.

No network: the tenant is faked with a locally generated RSA key, and discovery
and the JWKS endpoint are monkeypatched. Everything else — the state cookie,
PKCE, the token verification, the session cookie — is the production code path.
"""
import base64
import hashlib
import os
import time
import urllib.parse

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
# conftest's TestClient auto-signs every request with a dev header; the wiring
# test below needs a client that sends exactly what it is told to.
from fastapi.testclient import TestClient as _RawClient

import entra

TENANT = "a8bf01d5-f36b-4b08-ad19-18fe50aa833c"
CLIENT = "11111111-2222-3333-4444-555555555555"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"

META = {
    "authorization_endpoint": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize",
    "token_endpoint": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
    "jwks_uri": f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys",
    "issuer": ISSUER,
    "end_session_endpoint": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/logout",
}

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PEM = _OTHER_KEY.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption())


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    """Stands in for the tenant's published keys — always our test public key."""

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(_KEY.public_key())


@pytest.fixture(autouse=True)
def entra_env(monkeypatch):
    monkeypatch.setenv("ENTRA_TENANT_ID", TENANT)
    monkeypatch.setenv("ENTRA_CLIENT_ID", CLIENT)
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("ENTRA_REDIRECT_URI", "https://missions.test/auth/callback")
    monkeypatch.setenv("CITYOS_SESSION_SECRET", "test-session-secret-" + "x" * 32)
    monkeypatch.delenv("ENTRA_ALLOWED_DOMAINS", raising=False)
    monkeypatch.setattr(entra, "discovery", lambda: META)
    monkeypatch.setattr(entra, "_jwks_client", _FakeJWKClient)
    yield


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(entra.router)
    with TestClient(app, base_url="https://missions.test", follow_redirects=False) as c:
        yield c


def _id_token(*, nonce, key=_PRIVATE_PEM, aud=CLIENT, iss=ISSUER, tid=TENANT,
              email="shellyf@mashcal.co.il", name="שלי", exp_delta=600):
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "iat": now, "nbf": now, "exp": now + exp_delta,
              "nonce": nonce, "tid": tid, "oid": "user-object-id",
              "preferred_username": email, "name": name}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


def _start_login(client, next_path="/"):
    """Drive /auth/login and return (redirect_url, planted_state_claims)."""
    r = client.get("/auth/login", params={"next": next_path})
    assert r.status_code == 302, r.text
    planted = entra._unsign(client.cookies[entra.STATE_COOKIE])
    return r.headers["location"], planted


def _complete_login(client, monkeypatch, token_factory=None, **token_kw):
    """Full round trip: /auth/login, then a callback carrying a minted id_token."""
    _, planted = _start_login(client)
    factory = token_factory or _id_token
    token = factory(nonce=planted["nonce"], **token_kw)

    async def _fake_exchange(request, code, verifier):
        assert code == "the-code"
        assert verifier == planted["verifier"]  # PKCE verifier is the planted one
        return {"id_token": token}

    monkeypatch.setattr(entra, "_exchange_code", _fake_exchange)
    return client.get("/auth/callback", params={"code": "the-code", "state": planted["state"]})


# ── starting the login ───────────────────────────────────────────────

def test_login_redirects_to_entra_with_pkce_and_nonce(client):
    location, planted = _start_login(client)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    assert location.startswith(META["authorization_endpoint"])
    assert q["client_id"] == [CLIENT]
    assert q["response_type"] == ["code"]
    assert q["redirect_uri"] == ["https://missions.test/auth/callback"]
    assert q["state"] == [planted["state"]]
    assert q["nonce"] == [planted["nonce"]]
    # the challenge must really be S256(verifier), not the verifier itself
    assert q["code_challenge_method"] == ["S256"]
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(planted["verifier"].encode()).digest()).decode().rstrip("=")
    assert q["code_challenge"] == [expected]


def test_login_requires_configuration(client, monkeypatch):
    monkeypatch.delenv("ENTRA_CLIENT_SECRET")
    assert client.get("/auth/login").status_code == 500


def test_state_cookie_is_not_readable_by_script(client):
    _start_login(client)
    header = "; ".join(h for h in client.get("/auth/login").headers.get_list("set-cookie"))
    assert "HttpOnly" in header and "samesite=lax" in header.lower()


# ── the checks that make it real ─────────────────────────────────────

def test_happy_path_sets_a_session(client, monkeypatch):
    r = _complete_login(client, monkeypatch)
    assert r.status_code == 302, r.text
    assert r.headers["location"] == "/"
    assert entra.SESSION_COOKIE in client.cookies
    # and the session resolves back to the person Entra named
    request = type("R", (), {"cookies": {entra.SESSION_COOKIE: client.cookies[entra.SESSION_COOKIE]}})()
    assert entra.session_principal(request)["email"] == "shellyf@mashcal.co.il"


def test_mismatched_state_is_refused(client, monkeypatch):
    """Login CSRF: an attacker completing a login in someone else's browser."""
    _, planted = _start_login(client)

    async def _fake_exchange(request, code, verifier):
        return {"id_token": _id_token(nonce=planted["nonce"])}

    monkeypatch.setattr(entra, "_exchange_code", _fake_exchange)
    r = client.get("/auth/callback", params={"code": "the-code", "state": "attacker-state"})
    assert r.status_code == 400
    assert entra.SESSION_COOKIE not in client.cookies


def test_callback_without_a_state_cookie_is_refused(client):
    r = client.get("/auth/callback", params={"code": "x", "state": "y"})
    assert r.status_code == 400


def test_token_signed_by_another_key_is_refused(client, monkeypatch):
    r = _complete_login(client, monkeypatch, key=_OTHER_PEM)
    assert r.status_code == 401
    assert entra.SESSION_COOKIE not in client.cookies


def test_replayed_nonce_is_refused(client, monkeypatch):
    """A token minted for a different login attempt must not be accepted here."""
    def _wrong_nonce(nonce, **kw):
        return _id_token(nonce="a-nonce-from-somewhere-else", **kw)

    r = _complete_login(client, monkeypatch, token_factory=_wrong_nonce)
    assert r.status_code == 401


def test_token_for_another_audience_is_refused(client, monkeypatch):
    r = _complete_login(client, monkeypatch, aud="99999999-0000-0000-0000-000000000000")
    assert r.status_code == 401


def test_token_from_another_issuer_is_refused(client, monkeypatch):
    r = _complete_login(client, monkeypatch, iss="https://login.microsoftonline.com/evil/v2.0")
    assert r.status_code == 401


def test_expired_token_is_refused(client, monkeypatch):
    r = _complete_login(client, monkeypatch, exp_delta=-3600)
    assert r.status_code == 401


def test_token_from_another_tenant_is_refused(client, monkeypatch):
    r = _complete_login(client, monkeypatch, tid="ffffffff-0000-0000-0000-000000000000")
    assert r.status_code == 403


def test_domain_allowlist_keeps_outsiders_out(client, monkeypatch):
    monkeypatch.setenv("ENTRA_ALLOWED_DOMAINS", "mashcal.co.il")
    assert _complete_login(client, monkeypatch, email="guest@gmail.com").status_code == 403


def test_domain_allowlist_admits_the_domain(client, monkeypatch):
    monkeypatch.setenv("ENTRA_ALLOWED_DOMAINS", "mashcal.co.il, hodhasharon.gov.il")
    assert _complete_login(client, monkeypatch, email="Dana@Mashcal.co.il").status_code == 302


def test_account_without_an_email_claim_is_refused(client, monkeypatch):
    def _no_email(nonce, **kw):
        token = _id_token(nonce=nonce, **kw)
        claims = jwt.decode(token, options={"verify_signature": False})
        claims.pop("preferred_username")
        return jwt.encode(claims, _PRIVATE_PEM, algorithm="RS256", headers={"kid": "test-key"})

    assert _complete_login(client, monkeypatch, token_factory=_no_email).status_code == 403


# ── the session cookie ───────────────────────────────────────────────

def _principal_from(raw):
    return entra.session_principal(type("R", (), {"cookies": {entra.SESSION_COOKIE: raw}})())


def test_session_cookie_is_httponly_and_lax(client, monkeypatch):
    r = _complete_login(client, monkeypatch)
    cookie = next(h for h in r.headers.get_list("set-cookie") if h.startswith(entra.SESSION_COOKIE))
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    assert "Secure" in cookie  # base_url is https


def test_secure_flag_survives_a_tls_terminating_proxy(monkeypatch):
    """On Container Apps the app sees http even though the browser used https."""
    app = FastAPI()
    app.include_router(entra.router)
    with TestClient(app, base_url="http://internal.local", follow_redirects=False) as c:
        # plain local development: no https anywhere, so no Secure — otherwise
        # the cookie would be set and never sent back, and login would loop.
        monkeypatch.setenv("ENTRA_REDIRECT_URI", "http://localhost:8000/auth/callback")
        assert "Secure" not in c.get("/auth/login").headers.get_list("set-cookie")[0]

        # the edge tells us the browser used https, even though we hear http
        behind_proxy = c.get("/auth/login", headers={"X-Forwarded-Proto": "https"})
        assert "Secure" in behind_proxy.headers.get_list("set-cookie")[0]

        # and an https redirect URI alone is enough to infer it
        monkeypatch.setenv("ENTRA_REDIRECT_URI", "https://missions.test/auth/callback")
        assert "Secure" in c.get("/auth/login").headers.get_list("set-cookie")[0]


def test_tampered_session_cookie_is_ignored():
    raw = entra._sign({"email": "shellyf@mashcal.co.il", "name": "שלי"}, 3600)
    head, payload, sig = raw.split(".")
    forged = ".".join([head, base64.urlsafe_b64encode(b'{"email":"admin@mashcal.co.il"}')
                       .decode().rstrip("="), sig])
    assert _principal_from(forged) is None


def test_unsigned_session_cookie_is_ignored():
    """alg=none is the classic JWT bypass; PyJWT must reject it, so assert it."""
    forged = jwt.encode({"email": "admin@mashcal.co.il", "exp": int(time.time()) + 3600},
                        key="", algorithm="none")
    assert _principal_from(forged) is None


def test_expired_session_cookie_is_ignored():
    assert _principal_from(entra._sign({"email": "shellyf@mashcal.co.il"}, -1)) is None


def test_missing_session_cookie_is_not_an_error():
    assert entra.session_principal(type("R", (), {"cookies": {}})()) is None


# ── open redirect ────────────────────────────────────────────────────

@pytest.mark.parametrize("hostile", [
    "//evil.example",                 # protocol-relative — absolute to a browser
    "https://evil.example",
    "http://evil.example/path",
    "\\\\evil.example",
])
def test_next_cannot_leave_the_site(hostile):
    assert entra._safe_next(hostile) == "/"


def test_next_keeps_a_local_path():
    assert entra._safe_next("/board/7#item-3") == "/board/7#item-3"


def test_login_next_is_sanitised_before_it_is_stored(client):
    _, planted = _start_login(client, next_path="https://evil.example")
    assert planted["next"] == "/"


# ── logout ───────────────────────────────────────────────────────────

def test_logout_is_harmless_when_discovery_is_unreachable(client, monkeypatch):
    """Signing out must always clear our cookie, even if Entra is down."""
    _complete_login(client, monkeypatch)
    monkeypatch.setattr(entra, "discovery", _unreachable)
    r = client.get("/auth/logout")
    assert r.status_code == 302
    assert not client.cookies.get(entra.SESSION_COOKIE)


def _unreachable():
    from fastapi import HTTPException
    raise HTTPException(502, "down")


def test_logout_clears_the_session_and_ends_the_entra_one(client, monkeypatch):
    _complete_login(client, monkeypatch)
    r = client.get("/auth/logout")
    assert r.status_code == 302
    assert r.headers["location"].startswith(META["end_session_endpoint"])
    assert not client.cookies.get(entra.SESSION_COOKIE)


# ── the mode, wired into the real app ────────────────────────────────

def test_auth_mode_accepts_entra(monkeypatch):
    import auth
    monkeypatch.setenv("CITYOS_AUTH_MODE", "entra")
    assert auth.auth_mode() == "entra"
    # anything unrecognised still falls back to the strictest mode
    monkeypatch.setenv("CITYOS_AUTH_MODE", "banana")
    assert auth.auth_mode() == "easyauth"


def test_entra_session_signs_you_into_the_real_app(monkeypatch):
    """End to end: the session cookie maps to a User row and opens /api/.

    Guards the seam between this module and auth.resolve_user — the SSO could
    verify tokens perfectly and still sign nobody in if that lookup is wrong.
    """
    import main as cityos_main
    raw = _RawClient(cityos_main.app)

    # this one read happens in dev mode, which is honoured only for a locally
    # served app — the raw client would otherwise present itself as remote
    known = raw.get("/api/users",
                    headers={"X-CityOS-User": "1", "host": "localhost"}).json()[0]["email"]
    monkeypatch.setenv("CITYOS_AUTH_MODE", "entra")

    # no cookie at all → refused, and the dev header no longer works either
    assert raw.get("/api/auth/me").status_code == 401
    assert raw.get("/api/auth/me", headers={"X-CityOS-User": "1"}).status_code == 401

    raw.cookies.set(entra.SESSION_COOKIE, entra._sign({"email": known, "name": "x"}, 3600))
    me = raw.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["email"] == known
    assert me.json()["auth_mode"] == "entra"

    # a verified Entra identity with no account here is a clear 403, not a 401
    raw.cookies.set(entra.SESSION_COOKIE, entra._sign({"email": "nobody@mashcal.co.il"}, 3600))
    assert raw.get("/api/boards").status_code == 403
