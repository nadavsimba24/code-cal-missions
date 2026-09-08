"""Entra ID single sign-on for CityOS — the app performs the login itself.

This is the third identity source alongside the two in `auth.py`. Where
`easyauth` lets the Azure ingress do the OpenID Connect dance and hands us the
result in a header, this module runs the dance in-process:

    /auth/login     → redirect to Entra with state + nonce + PKCE
    /auth/callback  → swap the code for tokens, verify the id_token, set a
                      signed session cookie
    /auth/logout    → drop the cookie and end the Entra session

The advantage is that it works wherever the app runs — a laptop, Container
Apps, Railway, Vercel — because nothing outside the process has to be
configured. The cost is that we are now responsible for validating the token
ourselves, which is what most of this file is about.

What is verified on every sign-in, in order:

  1. `state` matches one of the values we planted in a short-lived cookie —
     without this, an attacker can complete a login *they* started in the
     victim's browser (login CSRF), silently making them act as someone else.
     A callback that matches none of them is never exchanged; it simply starts
     a clean login, because two tabs are far likelier than an attacker.
  2. The code exchange happens server-to-server with the client secret, so the
     browser never holds a token. PKCE rides along too: it costs one hash and
     removes the value of a stolen authorization code.
  3. The id_token signature is checked against the tenant's published JWKS
     (RS256), with issuer and audience pinned. An unverified id_token is just
     a JSON blob the browser could have written.
  4. `nonce` matches, which binds the token to this particular login attempt
     and stops a token minted elsewhere from being replayed here.
  5. `tid` matches the configured tenant — belt and braces for the issuer
     check, and the thing that actually keeps a stranger's tenant out when the
     app registration is multi-tenant.

Only then is the email handed to `auth.resolve_user`, which decides whether
that person has an account. Authentication answers "who are you"; the existing
permission model still answers "what may you do".
"""
import base64
import hashlib
import html
import os
import secrets
import time
import urllib.parse

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

SESSION_COOKIE = "cityos_session"
STATE_COOKIE = "cityos_oidc_state"
# The login round-trip is a few seconds of human time; ten minutes is already
# generous and keeps a stale tab from completing a login much later.
STATE_TTL_SECONDS = 600
DEFAULT_SESSION_HOURS = 8
# A browser can easily have more than one sign-in in flight: a second tab, an
# old tab whose polling hit 401 while she was signing in in this one, a
# double-clicked login. The state cookie used to hold only the newest attempt,
# so whichever tab came back second was compared against a state it had never
# seen and died on "אימות בקשת ההתחברות נכשל". It now carries the last few
# attempts and the callback matches against any of them — each one still has
# its own nonce and PKCE verifier, so nothing is loosened by remembering four
# instead of one.
MAX_PENDING_LOGINS = 4
# Marks a login that is already a second attempt. It rides inside the `state`
# we hand Entra, which comes back to us verbatim, rather than in a cookie —
# deliberately, because "this browser stores no cookie" is exactly the case
# where a cookie-based retry marker would loop for ever.
RETRY_MARK = "~retry"

_discovery_cache = {}
_jwks_clients = {}


# ── configuration ────────────────────────────────────────────────────

def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


def tenant_id():
    return _env("ENTRA_TENANT_ID")


def client_id():
    return _env("ENTRA_CLIENT_ID")


def client_secret():
    return _env("ENTRA_CLIENT_SECRET")


def allowed_domains():
    """Restrict sign-in to these email domains, e.g. `mashcal.co.il`.

    Empty means "any account the app registration itself lets in" — which for a
    single-tenant registration is already the tenant's own directory. This is a
    second fence for the case where the registration is multi-tenant or has
    guests, and it is the switch that makes this "domain users only".
    """
    raw = _env("ENTRA_ALLOWED_DOMAINS")
    return [d.strip().lower().lstrip("@") for d in raw.split(",") if d.strip()]


def is_configured():
    return bool(tenant_id() and client_id() and client_secret())


def _session_secret():
    """Key for the session cookie's signature.

    Falling back to a random per-process value is deliberate: it keeps a
    misconfigured deployment *working but forgetful* (everyone is signed out on
    restart) instead of signing cookies with a guessable constant. Set
    CITYOS_SESSION_SECRET in production, and the same value on every replica —
    otherwise instances cannot read each other's cookies.
    """
    secret = _env("CITYOS_SESSION_SECRET")
    if secret:
        # HS256's security is the key's, and a short one is brute-forceable
        # offline by anyone holding a cookie. Warn loudly rather than silently
        # signing sessions with something guessable.
        global _WARNED_SHORT_SECRET
        if len(secret.encode()) < 32 and not _WARNED_SHORT_SECRET:
            _WARNED_SHORT_SECRET = True
            print("[auth] CITYOS_SESSION_SECRET is shorter than 32 bytes — session "
                  "cookies are weakly signed. Generate one with: openssl rand -base64 48")
        return secret
    global _EPHEMERAL_SECRET
    if not _EPHEMERAL_SECRET:
        _EPHEMERAL_SECRET = secrets.token_urlsafe(48)
        print("[auth] CITYOS_SESSION_SECRET is not set — using a random per-process "
              "key. Sessions will not survive a restart or span replicas.")
    return _EPHEMERAL_SECRET


_EPHEMERAL_SECRET = None
_WARNED_SHORT_SECRET = False


def _session_hours():
    try:
        return max(1, int(_env("CITYOS_SESSION_HOURS", str(DEFAULT_SESSION_HOURS))))
    except ValueError:
        return DEFAULT_SESSION_HOURS


# ── OpenID Connect discovery ─────────────────────────────────────────

def _authority():
    return f"https://login.microsoftonline.com/{tenant_id()}/v2.0"


def discovery():
    """The tenant's OIDC metadata, fetched once and cached for the process."""
    tid = tenant_id()
    if not tid:
        raise HTTPException(500, "ENTRA_TENANT_ID is not configured")
    if tid not in _discovery_cache:
        url = f"{_authority()}/.well-known/openid-configuration"
        try:
            resp = httpx.get(url, timeout=10)
            resp.raise_for_status()
            _discovery_cache[tid] = resp.json()
        except Exception as exc:
            raise HTTPException(502, f"לא ניתן להתחבר לשרת הזיהוי של הארגון: {exc}")
    return _discovery_cache[tid]


def _jwks_client():
    """PyJWKClient caches keys and refetches on an unknown kid (key rollover)."""
    uri = discovery()["jwks_uri"]
    if uri not in _jwks_clients:
        _jwks_clients[uri] = jwt.PyJWKClient(uri, cache_keys=True)
    return _jwks_clients[uri]


# ── the state cookie (CSRF + PKCE + where to go back to) ─────────────

def _sign(payload: dict, ttl_seconds: int) -> str:
    now = int(time.time())
    return jwt.encode({**payload, "iat": now, "exp": now + ttl_seconds},
                      _session_secret(), algorithm="HS256")


def _unsign(token: str) -> dict:
    return jwt.decode(token, _session_secret(), algorithms=["HS256"])


def _pending_logins(request: Request) -> list:
    """The sign-ins this browser currently has in flight, newest first.

    Never raises: a missing, expired or unreadable cookie simply means "none",
    which the callback handles by starting a fresh login rather than by
    showing an error.
    """
    raw = request.cookies.get(STATE_COOKIE)
    if not raw:
        return []
    try:
        claims = _unsign(raw)
    except jwt.PyJWTError:
        return []
    attempts = claims.get("attempts")
    if not isinstance(attempts, list):
        # A cookie planted by the earlier single-attempt format, still in a
        # browser mid-login while this version deploys.
        attempts = [claims] if claims.get("state") else []
    cutoff = int(time.time()) - STATE_TTL_SECONDS
    return [a for a in attempts
            if isinstance(a, dict) and a.get("state") and a.get("ts", cutoff + 1) > cutoff]


def _match_attempt(pending: list, returned_state: str):
    """The attempt this callback belongs to, or None if it belongs to none of them."""
    if not returned_state:
        return None
    for attempt in pending:
        if secrets.compare_digest(str(attempt.get("state", "")), returned_state):
            return attempt
    return None


def _safe_next(raw: str) -> str:
    """Only ever redirect to a path on this site.

    `//evil.com` and `https://evil.com` are both absolute once a browser reads
    them, so an open redirect here would let a phishing link launder itself
    through our domain. Anything that is not a single-slash path becomes "/".
    """
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw


def redirect_uris() -> list:
    """Every callback URI this deployment may legitimately use, in order."""
    return [u.strip() for u in _env("ENTRA_REDIRECT_URI").split(",") if u.strip()]


def _redirect_uri(request: Request) -> str:
    """Must match a Web redirect URI on the app registration, character for character.

    Prefer the explicit setting: behind a proxy the request's own scheme is
    often http even though the browser used https, and a mismatched redirect
    URI is the single most common cause of AADSTS50011.

    One site can answer on more than one hostname — a custom domain and the
    platform's own — and a cookie belongs to the host the browser typed, not to
    the site. Naming a redirect URI on the *other* host therefore sends the
    callback to a host that has never seen our state cookie, and the sign-in
    fails in a way that reads exactly like a browser blocking cookies. Prod hit
    this: people arrive on missions.mashcal.co.il and were sent back to the
    azurewebsites.net name. So the setting takes a comma-separated list and the
    URI on *this* request's host wins; a single value behaves as it always did.
    Every host in the list has to be registered on the app registration too, or
    that host's sign-in is AADSTS50011.
    """
    configured = redirect_uris()
    here = _external_base_url(request)
    if configured:
        host = urllib.parse.urlparse(here).netloc.lower()
        for uri in configured:
            if urllib.parse.urlparse(uri).netloc.lower() == host:
                return uri
        return configured[0]
    path = urllib.parse.urlparse(str(request.url_for("entra_callback"))).path
    return here + path


def _is_https(request: Request) -> bool:
    """Is the *browser's* connection https, not just ours?

    Container Apps, Railway and Vercel all terminate TLS at the edge and speak
    plain http to the app, so `request.url.scheme` says http on a site the user
    reached over https — and the session cookie would silently lose its Secure
    flag exactly where it matters most. The forwarded header is safe to trust
    for this one decision: believing it can only add Secure, never remove it,
    and a client that lies about it merely breaks its own session.
    """
    if request.url.scheme == "https":
        return True
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if forwarded:
        return forwarded == "https"
    # Last resort: an https redirect URI means the deployment is https.
    return any(u.startswith("https://") for u in redirect_uris())


def _external_base_url(request: Request) -> str:
    """The origin the *browser* used — `https://host`, not the one we were handed.

    App Service and Container Apps both terminate TLS at their front end and
    speak plain http to the container, and uvicorn only believes forwarding
    headers from 127.0.0.1, which is never the address those front ends connect
    from. So `request.base_url` reads http on a site that cannot be reached over
    http at all. Entra compares redirect URIs as strings, so that single wrong
    scheme is the whole difference between a working sign-out and AADSTS50011.
    """
    host = (request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or request.url.netloc)
    host = host.split(",")[0].strip()
    scheme = "https" if _is_https(request) else request.url.scheme
    return f"{scheme}://{host}"


def _cookie_kwargs(request: Request, max_age: int):
    # Secure is conditional only so that http://localhost still works in
    # development; anything reached over https gets it.
    return {
        "httponly": True,
        "secure": _is_https(request),
        "samesite": "lax",
        "path": "/",
        "max_age": max_age,
    }


# ── routes ───────────────────────────────────────────────────────────

@router.get("/auth/login")
def entra_login(request: Request, next: str = "/", retry: int = 0):
    """Start the sign-in: park a state cookie, then hand the browser to Entra."""
    try:
        return _start_login(request, next, retry)
    except HTTPException as exc:
        return _auth_error(exc.status_code, exc.detail)


def _start_login(request: Request, next: str, retry: int):
    if not is_configured():
        raise HTTPException(500, "התחברות Entra אינה מוגדרת — חסרים ENTRA_TENANT_ID / "
                                 "ENTRA_CLIENT_ID / ENTRA_CLIENT_SECRET")
    meta = discovery()

    state = secrets.token_urlsafe(24) + (RETRY_MARK if retry else "")
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")

    params = {
        "client_id": client_id(),
        "response_type": "code",
        "redirect_uri": _redirect_uri(request),
        "response_mode": "query",
        # openid+profile+email is all we need: this app authenticates people, it
        # does not call Graph on their behalf. Asking for less means the consent
        # prompt is trivial and a leaked token is worth nothing.
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    resp = RedirectResponse(meta["authorization_endpoint"] + "?" + urllib.parse.urlencode(params),
                            status_code=302)
    attempt = {"state": state, "nonce": nonce, "verifier": verifier,
               "next": _safe_next(next), "ts": int(time.time())}
    # Newest first, and the older ones kept: see MAX_PENDING_LOGINS. Trimming
    # to the cap here is what stops a browser that keeps starting logins from
    # growing the cookie without bound.
    pending = [attempt] + _pending_logins(request)
    resp.set_cookie(STATE_COOKIE,
                    _sign({"attempts": pending[:MAX_PENDING_LOGINS]}, STATE_TTL_SECONDS),
                    **_cookie_kwargs(request, STATE_TTL_SECONDS))
    return resp


@router.get("/auth/callback", name="entra_callback")
async def entra_callback(request: Request):
    """Entra sends the browser back here with a one-time code."""
    try:
        return await _complete_login(request)
    except HTTPException as exc:
        # A person who has just been bounced through Entra should not land on a
        # raw JSON body. Same status, readable page.
        return _auth_error(exc.status_code, exc.detail)


async def _complete_login(request: Request):
    params = request.query_params
    if params.get("error"):
        detail = params.get("error_description") or params.get("error")
        raise HTTPException(401, f"ההתחברות נכשלה: {detail}")

    code = params.get("code")
    if not code:
        raise HTTPException(400, "חסר קוד הרשאה מהשרת של Entra")

    # Login CSRF check: this must be one of the logins *this* browser started.
    pending = _pending_logins(request)
    planted = _match_attempt(pending, params.get("state", ""))
    if not planted:
        # The cookie is gone (a bookmarked callback URL, a login left open past
        # the TTL, cookies cleared) or it holds only other attempts. Both are
        # ordinary, and both look identical to the one case that is not — a
        # login someone else started in this browser. So the code is thrown
        # away unused and a clean login begins; what must never happen, and
        # still does not, is exchanging a code for an attempt we cannot vouch
        # for. That check is the whole point of `state`.
        return _restart_login(request, pending, params.get("state", ""))

    tokens = await _exchange_code(request, code, planted["verifier"])
    claims = _verify_id_token(tokens.get("id_token"), planted["nonce"])
    principal = _principal_from_claims(claims)

    email = principal["email"]
    domains = allowed_domains()
    if domains and email.split("@")[-1] not in domains and not _is_invited_guest(email):
        raise HTTPException(403, "החשבון אינו שייך לדומיין של הארגון")

    hours = _session_hours()
    resp = RedirectResponse(_safe_next(planted.get("next", "/")), status_code=302)
    resp.set_cookie(SESSION_COOKIE,
                    _sign({"email": email, "name": principal["name"], "oid": claims.get("oid")},
                          hours * 3600),
                    **_cookie_kwargs(request, hours * 3600))
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp


def _restart_login(request: Request, pending: list, returned_state: str):
    """No attempt matched — heal it instead of dead-ending on an error page.

    Once, though. If the login we send them on comes back unmatched again the
    browser is not keeping our cookie at all (third-party cookie blocking, a
    private window with everything off), and bouncing a second time would spin
    for ever instead of saying so.
    """
    reason = ("no sign-in is pending in this browser" if not pending
              else f"state matches none of the {len(pending)} pending sign-ins")
    if returned_state.endswith(RETRY_MARK):
        print(f"[auth] sign-in failed after a retry: {reason}")
        return _auth_error(400, "לא הצלחנו להשלים את ההתחברות. ייתכן שהדפדפן חוסם עוגיות "
                                "עבור האתר — אפשר לנסות שוב, או לפתוח חלון רגיל (לא פרטי).")

    # A tab that was left open and only now finished a login it started before
    # she signed in in another tab: she is already in, so just let her through.
    nxt = _safe_next(pending[0].get("next", "/")) if pending else "/"
    if session_principal(request):
        print(f"[auth] callback ignored, session already valid: {reason}")
        return RedirectResponse(nxt, status_code=302)

    print(f"[auth] restarting sign-in: {reason}")
    return RedirectResponse("/auth/login?retry=1&next=" + urllib.parse.quote(nxt, safe=""),
                            status_code=302)


_ERROR_PAGE = """<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ההתחברות נכשלה</title>
<style>
  body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#f6f7fb;color:#323338;
       font-family:"Segoe UI",Rubik,Arial,Helvetica,sans-serif}}
  .card{{background:#fff;border-radius:12px;padding:36px 40px;max-width:440px;
        box-shadow:0 8px 28px rgba(0,0,0,.10);text-align:center}}
  h1{{margin:0 0 12px;font-size:20px}}
  p{{margin:0 0 24px;font-size:15px;line-height:1.6;color:#676879}}
  a{{display:inline-block;background:#0073ea;color:#fff;text-decoration:none;
     padding:10px 26px;border-radius:6px;font-size:15px}}
</style></head>
<body><div class="card">
  <h1>ההתחברות נכשלה</h1>
  <p>{message}</p>
  <a href="/auth/login">התחברות מחדש</a>
</div></body></html>
"""


def _auth_error(status: int, message) -> HTMLResponse:
    """The same status, in something a person can read and act on."""
    return HTMLResponse(_ERROR_PAGE.format(message=html.escape(str(message))),
                        status_code=status)


async def _exchange_code(request: Request, code: str, verifier: str) -> dict:
    """Swap the authorization code for tokens — server to server, with the secret."""
    meta = discovery()
    data = {
        "client_id": client_id(),
        "client_secret": client_secret(),
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(request),
        "code_verifier": verifier,
        "scope": "openid profile email",
    }
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.post(meta["token_endpoint"], data=data)
    if resp.status_code != 200:
        # Entra's error body names the misconfiguration (AADSTS…), and this is
        # a server-side log, not something the browser is shown.
        print(f"[auth] token exchange failed {resp.status_code}: {resp.text[:400]}")
        raise HTTPException(401, "החלפת קוד ההרשאה מול Entra נכשלה")
    return resp.json()


def _verify_id_token(id_token: str, expected_nonce: str) -> dict:
    """Signature, issuer, audience, expiry, nonce and tenant — all of them."""
    if not id_token:
        raise HTTPException(401, "לא התקבל אסימון זהות מ-Entra")
    try:
        key = _jwks_client().get_signing_key_from_jwt(id_token).key
    except Exception as exc:
        raise HTTPException(502, f"לא ניתן לאמת את חתימת האסימון: {exc}")

    try:
        claims = jwt.decode(
            id_token, key, algorithms=["RS256"],
            audience=client_id(),
            issuer=discovery()["issuer"].replace("{tenantid}", tenant_id()),
            options={"require": ["exp", "iat", "aud", "iss"]},
            leeway=60,  # tolerate modest clock skew between us and Entra
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"אסימון הזהות אינו תקין: {exc}")

    if not secrets.compare_digest(claims.get("nonce", ""), expected_nonce):
        raise HTTPException(401, "אימות האסימון נכשל (nonce)")

    tid = tenant_id()
    # A GUID tenant is pinned exactly. `organizations`/`common` cannot be pinned
    # this way by definition, and there the domain allowlist is the real fence.
    if "-" in tid and claims.get("tid") and claims["tid"].lower() != tid.lower():
        raise HTTPException(403, "החשבון שייך לארגון אחר")
    return claims


_EMAIL_CLAIMS = ("preferred_username", "email", "upn", "unique_name")


def _principal_from_claims(claims: dict) -> dict:
    candidates = [str(claims[c]).strip() for c in _EMAIL_CLAIMS
                  if claims.get(c) and "@" in str(claims[c])]
    # A B2B guest carries two addresses: the one they typed, and the mangled
    # `person_partner.com#EXT#@host.onmicrosoft.com` the directory built from
    # it. Which claim holds which varies by guest type, so prefer any claim that
    # is a real address and decode the #EXT# form only if that is all there is.
    # Without this a guest signs in perfectly and is then told they have no
    # account, because no users row is keyed by the mangled form.
    email = next((c for c in candidates if "#EXT#" not in c.upper()), None)
    if not email and candidates:
        from entra_guests import decode_ext_upn
        email = decode_ext_upn(candidates[0])
    if not email:
        raise HTTPException(403, "לא נמצאה כתובת דוא\"ל בפרופיל המשתמש ב-Entra")
    return {"email": str(email).strip().lower(), "name": claims.get("name")}


def _is_invited_guest(email: str) -> bool:
    """Was this address deliberately invited through the guests screen?

    The domain allowlist exists to keep strangers out, and a guest is by
    definition on somebody else's domain — so without this exception the
    feature would invite people into the tenant who then cannot sign in. The
    fence is not lowered: only an address a system admin invited, which is the
    only way a users row ever gets an `entra_object_id`, passes.

    Imported lazily, and never allowed to raise: an unavailable database must
    not turn into a confusing "wrong domain" message.
    """
    try:
        from auth import is_invited_guest
        return is_invited_guest(email)
    except Exception as exc:
        print(f"[auth] guest check failed for {email}: {exc}")
        return False


@router.get("/auth/logout")
def entra_logout(request: Request):
    """Clear our session, then end the Entra one.

    Skipping the second half is why "logout" used to be cosmetic: the next
    request would be silently signed back in from the still-live Entra session.
    """
    post_logout = _external_base_url(request) + "/"
    try:
        end_session = discovery().get("end_session_endpoint")
    except HTTPException:
        end_session = None
    target = (end_session + "?" + urllib.parse.urlencode({"post_logout_redirect_uri": post_logout})
              if end_session else "/")
    resp = RedirectResponse(target, status_code=302)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp


# ── what auth.py calls on every request ──────────────────────────────

def session_principal(request: Request):
    """{email, name} from the session cookie, or None if there isn't a valid one."""
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        claims = _unsign(raw)
    except jwt.PyJWTError:
        return None  # expired or tampered — treated as "not signed in"
    email = claims.get("email")
    if not email:
        return None
    return {"email": email, "name": claims.get("name")}
