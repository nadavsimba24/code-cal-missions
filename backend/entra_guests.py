"""Guest access — invite an external person into the tenant, and into one group.

`backend/entra.py` signs people in. This module is the other half of letting an
outsider *be* one of those people: it invites the address into Entra ID as a B2B
guest and puts the resulting directory object into a single group (by default
`missions-guests`), which is what an administrator can point at when asked "who
from outside can reach this system".

Everything here talks to Microsoft Graph **app-only** — client credentials, no
user in the loop — because the person clicking "הזמן אורח" in the app is a
CityOS system admin, not necessarily anyone with rights in the directory. The
credentials are the SSO app registration's by default; `ENTRA_GRAPH_*` overrides
each one if you would rather keep the two roles on separate registrations.

Two application permissions, admin-consented, are the whole requirement:

    User.Invite.All          POST /invitations
    GroupMember.ReadWrite.All  read the group, add and remove its members

The feature is off unless `ENTRA_GUEST_INVITES` is set, which is how it reaches
QA without also reaching production: both run the same image, and only the QA
Container App carries the variable. See scripts/ENTRA_GUESTS.md.

Nothing in here writes to our own database — main.py owns that, so that the
directory call and the local row are visibly two steps and the second one can
be skipped or repeated without re-inviting anybody.
"""
import os
import time

import httpx
from fastapi import HTTPException

GRAPH = "https://graph.microsoft.com/v1.0"
DEFAULT_GROUP = "missions-guests"
# A token is good for an hour; renewing a minute early costs nothing and takes
# clock skew and a slow request out of the picture.
TOKEN_SKEW_SECONDS = 60
TIMEOUT = 20

_token_cache = {}      # (tenant, client) → {"value", "expires_at"}
_group_cache = {}      # group name → object id


# ── configuration ────────────────────────────────────────────────────

def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


def _tenant_id():
    return _env("ENTRA_GRAPH_TENANT_ID") or _env("ENTRA_TENANT_ID")


def _client_id():
    return _env("ENTRA_GRAPH_CLIENT_ID") or _env("ENTRA_CLIENT_ID")


def _client_secret():
    return _env("ENTRA_GRAPH_CLIENT_SECRET") or _env("ENTRA_CLIENT_SECRET")


def group_name():
    """The one group every invited guest is put into."""
    return _env("ENTRA_GUEST_GROUP", DEFAULT_GROUP)


def group_id_override():
    """Pin the group by object id, skipping the lookup by display name.

    Worth setting: display names are not unique in Entra, so a second group that
    happens to share the name would make the lookup ambiguous — and this module
    refuses rather than guess which one you meant.
    """
    return _env("ENTRA_GUEST_GROUP_ID")


def is_enabled():
    """The feature switch. Off means the screen exists but the API declines."""
    return _env("ENTRA_GUEST_INVITES").lower() in ("1", "true", "yes", "on")


def is_configured():
    return bool(_tenant_id() and _client_id() and _client_secret())


def redirect_url():
    """Where Entra sends the guest after they redeem the invitation.

    Ours, so redeeming lands them in the app they were invited to rather than on
    the generic My Apps page. Falls back to the SSO redirect URI's origin, which
    is already configured everywhere this runs.
    """
    explicit = _env("ENTRA_GUEST_REDIRECT_URL")
    if explicit:
        return explicit
    first = _env("ENTRA_REDIRECT_URI").split(",")[0].strip()
    if first:
        # …/auth/callback → the site root. The callback itself is a terrible
        # landing page: it expects a code and would show the sign-in error card.
        return first.rsplit("/auth/callback", 1)[0] + "/" if "/auth/callback" in first else first
    return "https://myapps.microsoft.com"


def require_available():
    """Raise the reason this cannot run, or return quietly."""
    if not is_enabled():
        raise HTTPException(503, "הזמנת אורחים אינה מופעלת בסביבה זו "
                                 "(ENTRA_GUEST_INVITES)")
    if not is_configured():
        raise HTTPException(503, "הזמנת אורחים אינה מוגדרת — חסרים ENTRA_TENANT_ID / "
                                 "ENTRA_CLIENT_ID / ENTRA_CLIENT_SECRET")


# ── Microsoft Graph, app-only ────────────────────────────────────────

def _access_token():
    """A client-credentials token for Graph, cached until shortly before expiry."""
    key = (_tenant_id(), _client_id())
    cached = _token_cache.get(key)
    if cached and cached["expires_at"] > time.time():
        return cached["value"]
    url = f"https://login.microsoftonline.com/{_tenant_id()}/oauth2/v2.0/token"
    data = {
        "client_id": _client_id(),
        "client_secret": _client_secret(),
        "grant_type": "client_credentials",
        # .default means "every application permission already consented on this
        # registration" — the consent decision stays in Entra, where an admin
        # made it, instead of being re-stated here.
        "scope": "https://graph.microsoft.com/.default",
    }
    try:
        resp = httpx.post(url, data=data, timeout=TIMEOUT)
    except Exception as exc:
        raise HTTPException(502, f"לא ניתן להתחבר ל-Microsoft Graph: {exc}")
    if resp.status_code != 200:
        # The body names the misconfiguration (AADSTS7000215 = wrong secret,
        # AADSTS700016 = wrong client id). It is a server log, not a response.
        print(f"[guests] token request failed {resp.status_code}: {resp.text[:400]}")
        raise HTTPException(502, "אימות מול Microsoft Graph נכשל — בדוק את פרטי רישום האפליקציה")
    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise HTTPException(502, "Microsoft Graph לא החזיר אסימון גישה")
    _token_cache[key] = {
        "value": token,
        "expires_at": time.time() + max(60, int(payload.get("expires_in", 3600))) - TOKEN_SKEW_SECONDS,
    }
    return token


def _graph(method, path, *, json=None, params=None, expect=(200, 201, 204)):
    """One Graph call. Returns the parsed body, or None for 204."""
    url = path if path.startswith("http") else GRAPH + path
    headers = {"Authorization": f"Bearer {_access_token()}",
               "Content-Type": "application/json"}
    try:
        resp = httpx.request(method, url, headers=headers, json=json,
                             params=params, timeout=TIMEOUT)
    except Exception as exc:
        raise HTTPException(502, f"הקריאה ל-Microsoft Graph נכשלה: {exc}")
    if resp.status_code not in expect:
        raise _graph_error(method, url, resp)
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


def _graph_error(method, url, resp) -> HTTPException:
    """Turn a Graph failure into something an admin can act on.

    Graph's own message is the useful part — "Insufficient privileges" and
    "Invalid domain name in the request" are different problems with different
    fixes, and hiding both behind "שגיאה" wastes an afternoon.
    """
    code = message = ""
    try:
        err = (resp.json() or {}).get("error") or {}
        code, message = err.get("code") or "", err.get("message") or ""
    except Exception:
        message = resp.text[:200]
    print(f"[guests] {method} {url} → {resp.status_code} {code}: {message[:400]}")
    if resp.status_code in (401, 403):
        return HTTPException(502, "לרישום האפליקציה חסרות הרשאות ב-Entra "
                                  "(User.Invite.All ו-GroupMember.ReadWrite.All עם אישור מנהל). "
                                  f"Graph: {message[:160]}")
    return HTTPException(502, f"Microsoft Graph החזיר שגיאה: {message[:200] or resp.status_code}")


# ── the group ────────────────────────────────────────────────────────

def _odata_quote(value: str) -> str:
    """A single quote inside an OData string literal is doubled, not escaped."""
    return value.replace("'", "''")


def resolve_group_id():
    """The object id of the guests group, looked up once per process."""
    pinned = group_id_override()
    if pinned:
        return pinned
    name = group_name()
    if name in _group_cache:
        return _group_cache[name]
    data = _graph("GET", "/groups", params={
        "$filter": f"displayName eq '{_odata_quote(name)}'",
        "$select": "id,displayName",
        "$top": "2",
    })
    groups = (data or {}).get("value") or []
    if not groups:
        raise HTTPException(400, f"הקבוצה '{name}' לא נמצאה ב-Entra ID — צור אותה, "
                                 f"או הגדר ENTRA_GUEST_GROUP_ID")
    if len(groups) > 1:
        raise HTTPException(400, f"יש יותר מקבוצה אחת בשם '{name}' ב-Entra ID — "
                                 f"הגדר ENTRA_GUEST_GROUP_ID עם המזהה של הקבוצה הנכונה")
    _group_cache[name] = groups[0]["id"]
    return _group_cache[name]


def add_to_group(object_id: str) -> bool:
    """Put a directory object in the guests group. True if this call added it.

    Already being a member is the expected outcome of re-inviting somebody, so
    it is success, not an error — Graph says so with a 400 whose message is the
    only way to tell it apart from a real bad request.
    """
    gid = resolve_group_id()
    body = {"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{object_id}"}
    url = f"{GRAPH}/groups/{gid}/members/$ref"
    headers = {"Authorization": f"Bearer {_access_token()}",
               "Content-Type": "application/json"}
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=TIMEOUT)
    except Exception as exc:
        raise HTTPException(502, f"הוספת האורח לקבוצה נכשלה: {exc}")
    if resp.status_code in (200, 201, 204):
        return True
    if resp.status_code == 400 and "already exist" in resp.text.lower():
        return False
    raise _graph_error("POST", url, resp)


def remove_from_group(object_id: str) -> bool:
    """Take a directory object out of the guests group. False if it wasn't in it."""
    gid = resolve_group_id()
    url = f"{GRAPH}/groups/{gid}/members/{object_id}/$ref"
    headers = {"Authorization": f"Bearer {_access_token()}"}
    try:
        resp = httpx.delete(url, headers=headers, timeout=TIMEOUT)
    except Exception as exc:
        raise HTTPException(502, f"הסרת האורח מהקבוצה נכשלה: {exc}")
    if resp.status_code in (200, 204):
        return True
    if resp.status_code == 404:
        return False
    raise _graph_error("DELETE", url, resp)


def group_members():
    """Everyone currently in the guests group, as Graph sees them.

    The directory is the truth about invitation state — whether the person has
    redeemed, whether an admin removed them by hand — and our own table cannot
    know any of it. Reading it is what makes the screen honest.
    """
    gid = resolve_group_id()
    data = _graph("GET", f"/groups/{gid}/members", params={
        "$select": "id,displayName,mail,userPrincipalName,userType,externalUserState",
        "$top": "999",
    })
    out = []
    for m in (data or {}).get("value") or []:
        out.append({
            "object_id": m.get("id"),
            "name": m.get("displayName"),
            "email": guest_email(m),
            "user_type": m.get("userType"),
            # PendingAcceptance until they click the link in the invitation.
            "invite_state": m.get("externalUserState"),
        })
    return out


# ── inviting ─────────────────────────────────────────────────────────

def invite(email: str, display_name: str, *, send_email=True, message=""):
    """Invite an external address into the tenant as a B2B guest.

    Graph is idempotent enough here to lean on: inviting an address that is
    already a guest returns the existing directory object rather than creating a
    second one, which is exactly what re-sending an invitation should do.
    """
    body = {
        "invitedUserEmailAddress": email,
        "invitedUserDisplayName": display_name or email.split("@")[0],
        "inviteRedirectUrl": redirect_url(),
        "sendInvitationMessage": bool(send_email),
    }
    if send_email and message:
        body["invitedUserMessageInfo"] = {"customizedMessageBody": message[:1000]}
    data = _graph("POST", "/invitations", json=body, expect=(200, 201))
    invited = (data or {}).get("invitedUser") or {}
    object_id = invited.get("id")
    if not object_id:
        raise HTTPException(502, "Microsoft Graph לא החזיר את מזהה המשתמש שנוצר")
    return {
        "object_id": object_id,
        "invite_state": (data or {}).get("status"),
        # Only useful when sendInvitationMessage was false — then this link is
        # the invitation, and it is on the admin to pass it on.
        "redeem_url": (data or {}).get("inviteRedeemUrl"),
    }


def guest_email(directory_user: dict) -> str:
    """The address a guest actually signs in with, out of a Graph user object.

    A guest's `userPrincipalName` is the mangled `person_partner.com#EXT#@…`
    form, which is not an address anybody has ever typed. `mail` holds the real
    one, so it wins; the UPN is decoded only as a last resort.
    """
    mail = (directory_user.get("mail") or "").strip()
    if mail:
        return mail.lower()
    return decode_ext_upn(directory_user.get("userPrincipalName") or "")


def decode_ext_upn(upn: str) -> str:
    """`person_partner.com#EXT#@host.onmicrosoft.com` → `person@partner.com`.

    Entra builds a guest's UPN by replacing the @ of their real address with an
    underscore and appending `#EXT#@<host tenant>`. Undoing that gives back the
    address our own users table is keyed by — without it a guest signs in
    successfully and is then told they are not registered in the system.
    """
    upn = (upn or "").strip()
    if "#EXT#" not in upn.upper():
        return upn.lower()
    local = upn.split("#EXT#")[0]
    if "_" not in local:
        return upn.lower()
    name, _, domain = local.rpartition("_")
    return f"{name}@{domain}".lower()
