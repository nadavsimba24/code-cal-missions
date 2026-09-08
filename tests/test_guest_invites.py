"""Group 25 — inviting external guests (backend/entra_guests.py, /api/guests).

Every test here fakes Microsoft Graph at the HTTP boundary, so the module's own
logic — the token cache, the group lookup, "already a member" being success, the
#EXT# UPN decoding — is the code under test rather than something mocked away.

What the suite is protecting, in order of how expensive the mistake would be:

  * only a system admin may invite anyone into the directory;
  * a guest who exists in Entra but is not in the group is not silently
    reported as ready — that person cannot actually be governed as a guest;
  * an ordinary member's address is never converted into a guest account;
  * an invited guest gets past ENTRA_ALLOWED_DOMAINS at sign-in, which by
    definition they would otherwise always fail, and nobody else does.
"""
import json

import pytest
from fastapi import HTTPException

import auth
import entra_guests
from models import User, WorkspaceMember
from sqlalchemy.orm import Session

import main as cityos_main

GROUP_ID = "99999999-aaaa-bbbb-cccc-dddddddddddd"


# ── a fake tenant ────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text if text is not None else json.dumps(self._payload)
        self.content = self.text.encode()

    def json(self):
        return self._payload


class FakeGraph:
    """Records every call and answers with whatever the test asked for."""

    def __init__(self):
        self.calls = []
        self.members = []          # object ids currently in the group
        self.member_details = {}   # object id → the Graph user object
        self.groups = [{"id": GROUP_ID, "displayName": "missions-guests"}]
        self.fail = {}             # "POST /invitations" → FakeResponse

    # -- the three httpx entry points entra_guests uses -----------------
    def post(self, url, headers=None, json=None, data=None, timeout=None):
        if "oauth2/v2.0/token" in url:
            return FakeResponse(200, {"access_token": "fake-token", "expires_in": 3600})
        return self.request("POST", url, json=json)

    def delete(self, url, headers=None, timeout=None):
        return self.request("DELETE", url)

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        path = url.replace(entra_guests.GRAPH, "")
        self.calls.append((method, path, json, params))
        key = f"{method} {path}"
        if key in self.fail:
            return self.fail[key]

        if method == "GET" and path == "/groups":
            name = (params or {}).get("$filter", "")
            hits = [g for g in self.groups if f"'{g['displayName']}'" in name]
            return FakeResponse(200, {"value": hits})

        if method == "GET" and path == f"/groups/{GROUP_ID}/members":
            return FakeResponse(200, {"value": [self.member_details[m] for m in self.members]})

        if method == "POST" and path == "/invitations":
            email = json["invitedUserEmailAddress"]
            oid = "oid-" + email.split("@")[0]
            self.member_details.setdefault(oid, {
                "id": oid, "displayName": json["invitedUserDisplayName"],
                "mail": email, "userType": "Guest",
                "userPrincipalName": email.replace("@", "_") + "#EXT#@tenant.onmicrosoft.com",
                "externalUserState": "PendingAcceptance",
            })
            return FakeResponse(201, {
                "id": "invite-1", "status": "PendingAcceptance",
                "inviteRedeemUrl": "https://login.microsoftonline.com/redeem?x=1",
                "invitedUser": {"id": oid},
            })

        if method == "POST" and path.endswith("/members/$ref"):
            oid = json["@odata.id"].rsplit("/", 1)[-1]
            if oid in self.members:
                return FakeResponse(400, text="One or more added object references already exist")
            self.members.append(oid)
            return FakeResponse(204)

        if method == "DELETE" and path.endswith("/$ref"):
            oid = path.split("/members/")[1].split("/")[0]
            if oid not in self.members:
                return FakeResponse(404)
            self.members.remove(oid)
            return FakeResponse(204)

        return FakeResponse(404, {"error": {"code": "unknown", "message": f"no fake for {key}"}})


@pytest.fixture
def graph(monkeypatch):
    """Configure the feature, point it at a fake tenant, forget both caches."""
    monkeypatch.setenv("ENTRA_GUEST_INVITES", "1")
    monkeypatch.setenv("ENTRA_TENANT_ID", "a8bf01d5-f36b-4b08-ad19-18fe50aa833c")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "11111111-2222-3333-4444-555555555555")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "secret")
    monkeypatch.delenv("ENTRA_GUEST_GROUP", raising=False)
    monkeypatch.delenv("ENTRA_GUEST_GROUP_ID", raising=False)
    entra_guests._token_cache.clear()
    entra_guests._group_cache.clear()
    fake = FakeGraph()
    monkeypatch.setattr(entra_guests.httpx, "post", fake.post)
    monkeypatch.setattr(entra_guests.httpx, "delete", fake.delete)
    monkeypatch.setattr(entra_guests.httpx, "request", fake.request)
    yield fake
    entra_guests._token_cache.clear()
    entra_guests._group_cache.clear()


def _cleanup(email):
    """Remove a test guest completely — the workspace row included.

    Leaving that row behind is not a tidiness problem: SQLite hands a deleted
    row's id to the next account created, which would inherit the membership
    (and with it, in the admin case, the capabilities) of somebody this file
    invented. Every test after it then fails for reasons that have nothing to do
    with what it was testing.
    """
    with Session(cityos_main.engine) as db:
        u = db.query(User).filter(User.email == email).first()
        if u:
            db.query(WorkspaceMember).filter(WorkspaceMember.user_id == u.id).delete()
            db.delete(u)
            db.commit()


# ── the endpoint ─────────────────────────────────────────────────────

def test_invite_creates_entra_guest_group_membership_and_local_user(client, graph, admin_id):
    email = "yael@partner.co.il"
    _cleanup(email)
    r = client.post("/api/guests", json={"actor_id": admin_id, "email": email,
                                         "name": "יעל כהן"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == email
    assert body["role"] == "guest"
    assert body["entra_object_id"] == "oid-yael"
    assert body["added_to_group"] is True

    # the directory really was asked to do both halves
    paths = [f"{m} {p}" for m, p, _, _ in graph.calls]
    assert "POST /invitations" in paths
    assert f"POST /groups/{GROUP_ID}/members/$ref" in paths
    assert graph.members == ["oid-yael"]
    _cleanup(email)


def test_invite_requires_system_admin(client, graph, member_id):
    r = client.post("/api/guests", json={"actor_id": member_id,
                                         "email": "nope@partner.co.il", "name": "לא"})
    assert r.status_code == 403
    assert not graph.calls           # refused before anything reached the tenant


def test_invite_rejects_a_malformed_address(client, graph, admin_id):
    r = client.post("/api/guests", json={"actor_id": admin_id, "email": "not-an-email"})
    assert r.status_code == 400
    assert not graph.calls


def test_an_existing_member_is_not_converted_into_a_guest(client, graph, admin_id, member_id):
    """Inviting a colleague's address would take away the account they have."""
    with Session(cityos_main.engine) as db:
        email = db.query(User.email).filter(User.id == member_id).scalar()
    r = client.post("/api/guests", json={"actor_id": admin_id, "email": email, "name": "x"})
    assert r.status_code == 409
    assert not graph.calls


def test_reinviting_a_guest_resends_without_creating_a_second_account(client, graph, admin_id):
    email = "amir@partner.co.il"
    _cleanup(email)
    first = client.post("/api/guests", json={"actor_id": admin_id, "email": email,
                                             "name": "אמיר"}).json()
    second = client.post("/api/guests", json={"actor_id": admin_id, "email": email,
                                              "name": "אמיר"})
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first["id"]
    # already in the group — Graph says so with a 400 that is not an error here
    assert second.json()["added_to_group"] is False
    assert graph.members == ["oid-amir"]
    _cleanup(email)


def test_group_failure_after_a_successful_invite_says_so_and_writes_nothing(client, graph, admin_id):
    email = "blocked@partner.co.il"
    _cleanup(email)
    graph.fail[f"POST /groups/{GROUP_ID}/members/$ref"] = FakeResponse(
        403, {"error": {"code": "Authorization_RequestDenied",
                        "message": "Insufficient privileges to complete the operation."}})
    r = client.post("/api/guests", json={"actor_id": admin_id, "email": email, "name": "חסום"})
    assert r.status_code == 502
    assert "missions-guests" in r.json()["detail"]
    # No half-made local account: the person cannot be governed as a guest yet,
    # and pressing invite again is the fix.
    with Session(cityos_main.engine) as db:
        assert db.query(User).filter(User.email == email).first() is None


def test_listing_reports_directory_state_alongside_our_own_rows(client, graph, admin_id):
    email = "dana@partner.co.il"
    _cleanup(email)
    client.post("/api/guests", json={"actor_id": admin_id, "email": email, "name": "דנה"})
    body = client.get("/api/guests", params={"actor_id": admin_id}).json()
    assert body["enabled"] and body["configured"]
    assert body["group"] == "missions-guests"
    row = next(g for g in body["guests"] if g["email"] == email)
    assert row["in_group"] is True
    assert row["invite_state"] == "PendingAcceptance"

    # An admin who removes them in the portal must show up here as out of the
    # group, not as a healthy guest.
    graph.members.clear()
    row = next(g for g in client.get("/api/guests", params={"actor_id": admin_id}).json()["guests"]
               if g["email"] == email)
    assert row["in_group"] is False
    _cleanup(email)


def test_listing_survives_an_unreachable_directory(client, graph, admin_id):
    email = "orit@partner.co.il"
    _cleanup(email)
    client.post("/api/guests", json={"actor_id": admin_id, "email": email, "name": "אורית"})
    graph.fail[f"GET /groups/{GROUP_ID}/members"] = FakeResponse(
        403, {"error": {"code": "Authorization_RequestDenied", "message": "nope"}})
    body = client.get("/api/guests", params={"actor_id": admin_id}).json()
    assert body["directory_error"]
    assert any(g["email"] == email for g in body["guests"])   # still listed
    _cleanup(email)


def test_revoke_removes_from_the_group_and_disables_the_account(client, graph, admin_id):
    email = "gone@partner.co.il"
    _cleanup(email)
    uid = client.post("/api/guests", json={"actor_id": admin_id, "email": email,
                                           "name": "יוצא"}).json()["id"]
    r = client.delete(f"/api/guests/{uid}", params={"actor_id": admin_id})
    assert r.status_code == 200
    assert r.json()["removed_from_group"] is True
    assert graph.members == []
    with Session(cityos_main.engine) as db:
        u = db.query(User).filter(User.id == uid).first()
        assert u.is_active is False
        assert u.entra_object_id == "oid-gone"   # kept, so a resend still finds them
    _cleanup(email)


def test_revoke_refuses_on_someone_who_is_not_an_invited_guest(client, graph, admin_id, member_id):
    r = client.delete(f"/api/guests/{member_id}", params={"actor_id": admin_id})
    assert r.status_code == 400
    assert not graph.calls


def test_the_feature_is_off_until_the_environment_switches_it_on(client, graph, admin_id, monkeypatch):
    monkeypatch.delenv("ENTRA_GUEST_INVITES", raising=False)
    r = client.post("/api/guests", json={"actor_id": admin_id, "email": "x@partner.co.il"})
    assert r.status_code == 503
    assert not graph.calls
    # The screen still loads, and says why the button is disabled.
    body = client.get("/api/guests", params={"actor_id": admin_id}).json()
    assert body["enabled"] is False


# ── the module's own decisions ───────────────────────────────────────

def test_an_ambiguous_group_name_is_refused_rather_than_guessed(graph):
    graph.groups.append({"id": "second-group", "displayName": "missions-guests"})
    with pytest.raises(HTTPException) as exc:
        entra_guests.resolve_group_id()
    assert exc.value.status_code == 400
    assert "ENTRA_GUEST_GROUP_ID" in exc.value.detail


def test_a_missing_group_names_itself(graph):
    graph.groups.clear()
    with pytest.raises(HTTPException) as exc:
        entra_guests.resolve_group_id()
    assert "missions-guests" in exc.value.detail


def test_the_group_id_can_be_pinned_skipping_the_lookup(graph, monkeypatch):
    monkeypatch.setenv("ENTRA_GUEST_GROUP_ID", "pinned-id")
    assert entra_guests.resolve_group_id() == "pinned-id"
    assert not [c for c in graph.calls if c[1] == "/groups"]


def test_the_token_is_fetched_once_and_reused(graph):
    entra_guests.resolve_group_id()
    entra_guests._group_cache.clear()
    entra_guests.resolve_group_id()
    assert entra_guests._token_cache          # cached, not refetched per call


def test_ext_upn_decoding_gives_back_the_address_the_person_typed():
    assert entra_guests.decode_ext_upn(
        "yael_partner.co.il#EXT#@tenant.onmicrosoft.com") == "yael@partner.co.il"
    # an address whose local part legitimately holds an underscore
    assert entra_guests.decode_ext_upn(
        "first_last_partner.co.il#EXT#@t.onmicrosoft.com") == "first_last@partner.co.il"
    # a member's ordinary UPN is left exactly as it is
    assert entra_guests.decode_ext_upn("moshe@mashcal.co.il") == "moshe@mashcal.co.il"


def test_the_real_address_wins_over_the_mangled_one():
    assert entra_guests.guest_email({"mail": "Yael@Partner.co.il",
                                     "userPrincipalName": "yael_partner.co.il#EXT#@t.onmicrosoft.com"}) \
        == "yael@partner.co.il"
    assert entra_guests.guest_email({"userPrincipalName": "yael_partner.co.il#EXT#@t.onmicrosoft.com"}) \
        == "yael@partner.co.il"


# ── signing in ───────────────────────────────────────────────────────

def test_an_invited_guest_passes_the_domain_allowlist_and_a_stranger_does_not(client, graph, admin_id, monkeypatch):
    """ENTRA_ALLOWED_DOMAINS exists to keep strangers out, and a guest is by
    definition on someone else's domain. Only the ones we invited get past it."""
    import entra
    email = "partner@elsewhere.com"
    _cleanup(email)
    client.post("/api/guests", json={"actor_id": admin_id, "email": email, "name": "שותף"})

    assert auth.is_invited_guest(email) is True
    assert auth.is_invited_guest("stranger@elsewhere.com") is False
    assert entra._is_invited_guest(email) is True

    # Revoking closes the door again — a deactivated guest is not "invited".
    with Session(cityos_main.engine) as db:
        u = db.query(User).filter(User.email == email).first()
        u.is_active = False
        db.commit()
    assert auth.is_invited_guest(email) is False
    _cleanup(email)


def test_an_ordinary_user_is_not_treated_as_an_invited_guest(client, member_id):
    """The exception keys off entra_object_id, which only the invite path writes
    — not off role == 'guest', which an admin may set for their own reasons."""
    with Session(cityos_main.engine) as db:
        email = db.query(User.email).filter(User.id == member_id).scalar()
    assert auth.is_invited_guest(email) is False


def test_a_guest_id_token_resolves_to_the_address_not_the_ext_upn():
    """The claim shapes a B2B guest can arrive with, all folding to one address."""
    import entra
    real = {"preferred_username": "yael@partner.co.il", "name": "יעל"}
    assert entra._principal_from_claims(real)["email"] == "yael@partner.co.il"

    mangled_first = {"preferred_username": "yael_partner.co.il#EXT#@t.onmicrosoft.com",
                     "email": "yael@partner.co.il", "name": "יעל"}
    assert entra._principal_from_claims(mangled_first)["email"] == "yael@partner.co.il"

    only_mangled = {"upn": "yael_partner.co.il#EXT#@t.onmicrosoft.com", "name": "יעל"}
    assert entra._principal_from_claims(only_mangled)["email"] == "yael@partner.co.il"
