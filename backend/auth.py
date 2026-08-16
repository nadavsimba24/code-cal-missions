"""
Identity for CityOS — who is making this request?

Until now the answer came from the client: every endpoint took an `actor_id`
query/body parameter and trusted it, so `?actor_id=1` was system admin. This
module replaces that with an identity the client cannot choose.

Three modes, selected by CITYOS_AUTH_MODE:

  entra
      The app signs people in itself, against an Entra ID app registration:
      /auth/login → Entra → /auth/callback → a signed session cookie. Nothing
      outside the process has to be configured, so this works on any host —
      a laptop, Container Apps, Railway. See backend/entra.py and
      scripts/ENTRA_SSO.md.

  easyauth (default)
      Production on Azure Container Apps with Entra ID. The platform's built-in
      authentication ("Easy Auth") terminates the login at the ingress and injects
      the X-MS-CLIENT-PRINCIPAL* headers. It also STRIPS those headers from
      inbound client requests, which is what makes them trustworthy — but only
      when the Container App is configured to *require* authentication. If you
      leave it on "allow unauthenticated access", the headers become spoofable
      and this module is back to trusting the client. See scripts/AZURE_AUTH.md.

  dev
      Local development, no Entra tenant. Identity comes from an X-CityOS-User
      header (user id or email) that the frontend sends for the picked user.
      Enabled only by putting CITYOS_AUTH_MODE=dev in .env — which is gitignored
      and excluded from the image by .dockerignore, so it cannot reach production.

The default is `easyauth` deliberately: an unconfigured deployment denies every
request instead of granting every request. Failing closed is the whole point.

Whichever mode is active, the job here is identical and deliberately small:
turn the request into an email, look up the `User` row, and refuse if there
isn't one. Everything downstream — boards, environments, roles — is unchanged
and does not know or care how the identity arrived.
"""
import base64
import json
import os

from fastapi import HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import User

# Set by main.init_auth() once the engine exists — avoids a circular import.
_engine = None

# Claim types Entra may use for the user's email/UPN, best first.
_EMAIL_CLAIMS = (
    "preferred_username",
    "upn",
    "email",
    "emails",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
)
_NAME_CLAIMS = (
    "name",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
)


def init_auth(engine):
    """Give the auth layer a database engine (called once from main)."""
    global _engine
    _engine = engine


def auth_mode():
    mode = (os.environ.get("CITYOS_AUTH_MODE") or "easyauth").strip().lower()
    return mode if mode in ("dev", "entra", "easyauth") else "easyauth"


_LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]", "0.0.0.0", "host.docker.internal")

def _is_local(request: Request) -> bool:
    """Is this request being served to the machine the app runs on?"""
    host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    return host in _LOCAL_HOSTS


def effective_auth_mode(request: Request) -> str:
    """The mode this particular request is authenticated under.

    Dev mode hands identity to whoever asks for it — that is what the local
    user picker is. It is meant for a developer on their own machine, so it is
    honoured only when the app is being served locally. Anywhere reachable by
    someone else falls back to easyauth: identity comes from the platform, and
    a request without one is refused. Without this, shipping a .env with
    CITYOS_AUTH_MODE=dev to a host (which `vercel deploy` does, since it
    uploads the working directory) turns the picker into a public door.
    """
    mode = auth_mode()
    if mode == "dev" and not _is_local(request):
        return "easyauth"
    return mode


def _autoprovision():
    return (os.environ.get("CITYOS_AUTH_AUTOPROVISION") or "").strip() in ("1", "true", "yes")


def _claims_to_principal(claims):
    """Fold Easy Auth's [{typ, val}] claim list into {email, name}."""
    by_type = {}
    for c in claims or []:
        typ, val = (c or {}).get("typ"), (c or {}).get("val")
        if typ and val and typ not in by_type:
            by_type[typ] = val
    email = next((by_type[t] for t in _EMAIL_CLAIMS if by_type.get(t)), None)
    name = next((by_type[t] for t in _NAME_CLAIMS if by_type.get(t)), None)
    return {"email": email, "name": name}


def _principal_easyauth(request: Request):
    """Extract {email, name} from the headers Azure Easy Auth injects."""
    raw = request.headers.get("x-ms-client-principal")
    if raw:
        try:
            decoded = base64.b64decode(raw).decode("utf-8")
            payload = json.loads(decoded)
        except Exception:
            raise HTTPException(401, "זהות המשתמש אינה תקינה")
        principal = _claims_to_principal(payload.get("claims"))
        if principal["email"]:
            return principal
    # Fallback: Easy Auth also sets this flattened header, which for Entra ID is
    # the user's UPN. Useful when the principal blob has an unexpected shape.
    name_header = request.headers.get("x-ms-client-principal-name")
    if name_header:
        return {"email": name_header, "name": name_header}
    return None


DEV_COOKIE = "cityos_user"

def _principal_dev(request: Request):
    """Local development identity: X-CityOS-User is a user id or an email.

    The header only rides on requests the app makes itself (fetch). A browser
    fetching a URL on its own — <img src>, a download link, a new tab — sends
    no such header, so an uploaded avatar or attachment would come back 401 and
    render broken. The same value is therefore also accepted from a cookie,
    which the browser attaches to every request to this origin. Dev mode only:
    in easyauth the ingress injects its headers on those requests too.
    """
    raw = (request.headers.get("x-cityos-user") or "").strip()
    if not raw:
        raw = (request.cookies.get(DEV_COOKIE) or "").strip()
    if not raw:
        return None
    return {"email": raw, "name": None}


def _principal_entra(request: Request):
    """In-app SSO: identity comes from the session cookie we signed at /auth/callback.

    Imported lazily so that a deployment which never uses this mode does not
    pay for the import, and a missing optional dependency cannot break boot.
    """
    from entra import session_principal
    return session_principal(request)


_PRINCIPAL_SOURCES = {
    "dev": _principal_dev,
    "entra": _principal_entra,
    "easyauth": _principal_easyauth,
}


def resolve_user(db: Session, request: Request):
    """The authenticated User for this request, or raise 401/403.

    Never consults query parameters or the request body — identity comes only
    from the transport, which the browser cannot forge.
    """
    mode = effective_auth_mode(request)
    principal = _PRINCIPAL_SOURCES[mode](request)
    if not principal or not principal.get("email"):
        raise HTTPException(401, "נדרשת התחברות")

    ident = principal["email"].strip().lower()

    # Dev mode accepts a bare user id so the local picker keeps working.
    if mode == "dev" and ident.isdigit():
        user = db.query(User).filter(User.id == int(ident)).first()
    else:
        user = db.query(User).filter(func.lower(User.email) == ident).first()

    if not user:
        if _autoprovision() and "@" in ident:
            user = User(email=ident, name=(principal.get("name") or ident.split("@")[0]),
                        role="member", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            raise HTTPException(403, "המשתמש אינו רשום במערכת — פנה למנהל המערכת")

    if user.is_active is False:
        raise HTTPException(403, "החשבון אינו פעיל")
    return user


# ── FastAPI dependencies ─────────────────────────────────────────────

def current_user(request: Request) -> User:
    """Dependency: the authenticated User. Use where you need the whole row."""
    if _engine is None:
        raise HTTPException(500, "auth not initialised")
    with Session(_engine) as db:
        user = resolve_user(db, request)
        db.expunge(user)
        return user


def current_user_id(request: Request) -> int:
    """Dependency: the authenticated user's id — the replacement for `actor_id`."""
    return current_user(request).id
