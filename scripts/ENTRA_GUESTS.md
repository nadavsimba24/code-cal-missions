# Guest access — inviting people from outside the organization

An **אורח** is somebody who does not have an account in the tenant: a supplier, a
consultant, a contact at another municipality. The guests screen invites them
into Entra ID as a B2B guest, puts them in one group — `missions-guests` — and
opens an account for them here with the `guest` role.

They sign in with **their own** account. No password is created in this system,
and nothing about how they authenticate differs from an employee once the
invitation is redeemed.

```
מסך ניהול מערכת → אורחים → הזמנת אורח
        │
        ├─ POST /invitations                    → a guest object in the tenant
        ├─ POST /groups/{missions-guests}/members/$ref
        └─ a users row: role=guest, entra_object_id=<the object id>
```

Code: [`backend/entra_guests.py`](../backend/entra_guests.py) (Graph),
`/api/guests` in [`backend/main.py`](../backend/main.py) (the endpoints),
`SysAdmin.renderGuests` in the SPA (the screen).

## 1. The group

Create it once, in **Entra admin center → Groups → New group**:

| | |
|---|---|
| Group type | Security |
| Group name | `missions-guests` |
| Membership type | Assigned (**not** dynamic — the app adds members itself) |

The name is only a default; `ENTRA_GUEST_GROUP` overrides it. If two groups in
the directory share the name the app refuses to guess between them and asks for
`ENTRA_GUEST_GROUP_ID` instead — which is worth setting regardless, since it
turns the lookup into a no-op.

## 2. The app registration

Reuse the SSO registration (**Mashcal-Missions**). It needs two *application*
permissions, which is a different list from the delegated ones SSO uses:

| Permission | Type | What it is for |
|---|---|---|
| `User.Invite.All` | Application | `POST /invitations` |
| `GroupMember.ReadWrite.All` | Application | read the group, add and remove members |

**API permissions → Add a permission → Microsoft Graph → Application permissions**,
then **Grant admin consent** — without the consent step every call comes back 403
and the screen says so, naming both permissions.

Prefer to keep inviting on a separate registration? Set `ENTRA_GRAPH_TENANT_ID`,
`ENTRA_GRAPH_CLIENT_ID` and `ENTRA_GRAPH_CLIENT_SECRET`; each falls back to its
`ENTRA_*` equivalent when unset.

Also confirm **External Identities → External collaboration settings** permits
invitations: "Member users and users assigned to specific admin roles can invite
guest users" is enough, because the invitation is sent by the *application*.

### Email one-time passcode — turn it on, or half your guests cannot accept

**External Identities → All identity providers → Email one-time passcode.**

Creating the invitation is not the hard part; proving the invitee owns the
address is. Entra can do that three ways, and only one of them works for an
arbitrary domain:

| The invitee has | How they redeem |
|---|---|
| An Azure AD account (any tenant) | immediately, with their work sign-in |
| A Microsoft account | with that account |
| Neither — most gmail/yahoo/small-supplier addresses | **email one-time passcode only** |

With the passcode provider off, that third row gets *"there isn't a Microsoft
account for that address"* and simply cannot accept — the guest object exists,
it sits at `PendingAcceptance` for ever, and nothing in this application can
help, because the failure is upstream of us.

Tenants created after late 2021 have it on by default. Older ones do not, and
this tenant is one of them. Changing it needs Global Administrator or
Authentication Policy Administrator.

Diagnosing this from the outside: the guest's `externalUserState` staying at
`PendingAcceptance` after they say they accepted is the tell. Note that a guest
can *sign in* while still pending, using the `…#EXT#@…onmicrosoft.com` form of
their name — so "they got in once" does not mean redemption happened, and until
it does, their plain address is not a sign-in identifier.

## 3. Configuration

| Variable | Required | Notes |
|---|---|---|
| `ENTRA_GUEST_INVITES` | yes | `1` to switch the feature on. Unset ⇒ the screen loads, says it is off, and the API returns 503. This is what keeps it in QA. |
| `ENTRA_GUEST_GROUP` | no | Group display name. Default `missions-guests`. |
| `ENTRA_GUEST_GROUP_ID` | recommended | The group's object id. Pins it, and skips the display-name lookup. |
| `ENTRA_GUEST_REDIRECT_URL` | no | Where redeeming lands the guest. Defaults to the site root derived from `ENTRA_REDIRECT_URI`. |
| `ENTRA_GRAPH_*` | no | Separate credentials for Graph; each falls back to the `ENTRA_*` one. |

### `ENTRA_ALLOWED_DOMAINS` — leave it unset

Guests come from every domain there is, so an allowlist of organizational
domains is the wrong shape for them and is **not** set on an environment that
invites guests. Two fences still stand, and they are the ones doing the work:

1. **The tenant.** `ENTRA_TENANT_ID` is a GUID, so `entra._verify_id_token`
   pins the token's `tid` to that tenant. Only accounts *in* the Mashcal
   directory can sign in — employees and the guests invited into it. A stranger
   with a Google account is not one of them.
2. **The account.** `auth.resolve_user` refuses anybody with no `users` row —
   `המשתמש אינו רשום במערכת`. Only this screen and the users screen create one.

That second fence holds **only while `CITYOS_AUTH_AUTOPROVISION` is unset**. Set
it, and any account that passes fence 1 gets a `users` row on first sign-in with
role `member`. Do not turn it on alongside guests without narrowing it first.

The code still honours the variable, so re-adding it re-enables the fence.
`auth.is_invited_guest` then lets the invited guests past it, which is what
keeps them working when it is on — see `entra._complete_login`.

## 4. Turning it on in QA

QA is the `Missions-Qa-Webapp` **Web App** in `rg-missions-qa`, in the
**Misssions** subscription. (It was the Container App `missionspoccontainer`
until 2026-10-26; that app is still standing but nothing deploys to it any
more, so setting a variable on it now changes nothing.) The pipeline deploys
the image and touches only the handful of settings it stamps, so this is a
one-time manual step — and the reason the feature can ship to `main` without
appearing in production:

```bash
SUB=714d8f95-f2fa-4b06-942e-fb76ffb6d213     # "Misssions"

# The group's object id — copy it from the portal, or:
GROUP_ID=$(az ad group show --group missions-guests --query id -o tsv)

az webapp config appsettings set \
  --subscription "$SUB" \
  --resource-group rg-missions-qa \
  --name Missions-Qa-Webapp \
  --settings ENTRA_GUEST_INVITES=1 ENTRA_GUEST_GROUP_ID="$GROUP_ID"

az webapp config appsettings delete \
  --subscription "$SUB" \
  --resource-group rg-missions-qa \
  --name Missions-Qa-Webapp \
  --setting-names ENTRA_ALLOWED_DOMAINS
```

`appsettings set` merges, so `ENTRA_CLIENT_SECRET` and the rest survive.
Deleting `ENTRA_ALLOWED_DOMAINS` is what opens the app to guests from any
domain; see the section above for the two fences that stay standing. Both
commands restart the app; the image it runs does not change.

Production (`Missions-Prd-Webapp`) stays as it is. When it is time, the same two
settings go on with `az webapp config appsettings set`, which also merges.

## 5. What each side owns

Revoking removes the guest from the group and deactivates their account here. It
deliberately does **not** delete them from the tenant: that is a directory-wide
act with consequences in other applications, other groups and their files, and
it belongs in the portal, not behind a button on this screen.

The list reads the group live for each guest, so an administrator who removes
somebody in the portal sees them here as **אינו בקבוצה** rather than as a
healthy guest. When Graph cannot be reached the screen still lists whom we
invited and says plainly that the live state is missing — a stale "everything is
fine" would be worse than an admitted gap.
