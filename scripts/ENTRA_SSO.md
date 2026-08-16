# Entra ID SSO — the app signs people in itself

`CITYOS_AUTH_MODE=entra` makes the backend run the OpenID Connect flow against
your Entra ID app registration. Nothing outside the process needs configuring,
so it works the same on a laptop, on Container Apps, on Railway or anywhere else.

The alternative — letting the Azure ingress do it — is [AZURE_AUTH.md](AZURE_AUTH.md).
Pick one. They are the same login; the difference is who performs it.

```
GET /auth/login      → redirect to Entra, with state + nonce + PKCE
GET /auth/callback   → exchange the code, verify the id_token, set a session cookie
GET /auth/logout     → clear the cookie, then end the Entra session
```

Code: [`backend/entra.py`](../backend/entra.py). Identity mapping and the two other
modes: [`backend/auth.py`](../backend/auth.py).

## 1. The app registration

In **Entra admin center → App registrations → your app**:

| Setting | Value |
|---|---|
| Redirect URI | platform **Web**, `https://<your-host>/auth/callback` |
| | add `http://localhost:8000/auth/callback` for local development |
| Supported account types | Single tenant (`AzureADMyOrg`) — see the note below |
| Certificates & secrets | create a **client secret**, copy the *Value* (shown once) |
| Token configuration | nothing needed — `email`/`preferred_username` and `name` are in the default `profile`/`email` scopes |
| API permissions | nothing beyond the default `User.Read`; this app authenticates people, it does not call Graph |

The redirect URI must match **character for character**, including the scheme and
any trailing path. A mismatch is `AADSTS50011`, and it is the single most common
cause of a failed first setup.

Single tenant is what makes "domain users only" true at the directory level. If
the registration is multi-tenant for some other reason, set
`ENTRA_ALLOWED_DOMAINS` and the app enforces it a second time — the code checks
the `tid` claim against your tenant either way.

## 2. Configuration

```bash
CITYOS_AUTH_MODE=entra
ENTRA_TENANT_ID=a8bf01d5-f36b-4b08-ad19-18fe50aa833c   # Directory (tenant) ID
ENTRA_CLIENT_ID=<Application (client) ID>
ENTRA_CLIENT_SECRET=<the secret Value, not its ID>
ENTRA_REDIRECT_URI=https://<your-host>/auth/callback
ENTRA_ALLOWED_DOMAINS=mashcal.co.il                    # optional, comma separated
CITYOS_SESSION_SECRET=<openssl rand -base64 48>
CITYOS_SESSION_HOURS=8                                 # optional, default 8
```

| Variable | Required | Notes |
|---|---|---|
| `ENTRA_TENANT_ID` | yes | GUID, or `organizations`. A GUID is pinned against the token's `tid`. |
| `ENTRA_CLIENT_ID` | yes | Also the expected `aud` of the id_token. |
| `ENTRA_CLIENT_SECRET` | yes | Rotate before it expires — sign-in stops dead when it does. |
| `ENTRA_REDIRECT_URI` | recommended | Derived from the request if unset, which is wrong behind a TLS-terminating proxy (the app sees `http`). Set it. |
| `ENTRA_ALLOWED_DOMAINS` | no | Extra fence for guests / multi-tenant registrations. |
| `CITYOS_SESSION_SECRET` | production | Signs the session cookie. **Use the same value on every replica**, or instances cannot read each other's cookies and users bounce between signed-in and signed-out. Unset ⇒ a random per-process key ⇒ everyone is signed out on restart. |
| `CITYOS_SESSION_HOURS` | no | Session lifetime. When it expires the SPA silently bounces through `/auth/login`, which is invisible if the Entra session is still live. |

`ENTRA_CLIENT_SECRET` and `CITYOS_SESSION_SECRET` are credentials: they belong in
the platform's secret store (Container Apps secrets, Railway variables) or in
`.env` locally. `.env` is gitignored and excluded by `.dockerignore`.

## 3. Map the accounts before you switch it on

The verified Entra email is matched against `users.email`, case-insensitively.
The seeded directory uses `@hodhasharon.gov.il` while the tenant signs people in
as `@mashcal.co.il` — **nothing matches**, so the first sign-in after the switch
returns 403 for everyone, including whoever needs to fix it.

Give at least one workspace admin their real tenant address first:

```sql
UPDATE users SET email = 'shellyf@mashcal.co.il' WHERE id = 1;
```

Then onboard the rest either way:

- **Explicit (default, recommended)** — an admin adds each user in the app with
  the same email as their Entra account. Someone who signs in without a row gets
  a clear "המשתמש אינו רשום במערכת" rather than an empty app.
- **Automatic** — `CITYOS_AUTH_AUTOPROVISION=1` creates a `member` row on first
  successful sign-in. Only reasonable when the app registration is already
  restricted to the right group, otherwise everyone in the tenant gets an account.

## 4. Verify

```bash
# 1. the mode is live
curl -s https://<host>/api/status | python -m json.tool | grep auth_mode

# 2. the API is closed without a session
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/api/boards      # 401

# 3. the login really goes to your tenant and app
curl -s -o /dev/null -w '%{redirect_url}\n' https://<host>/auth/login
```

Then sign in with a browser. If it fails, the `AADSTS…` code in Entra's error
page names the cause; the server log also carries the token-exchange body.

| Symptom | Cause |
|---|---|
| `AADSTS50011` redirect URI mismatch | `ENTRA_REDIRECT_URI` ≠ what is registered |
| `AADSTS7000215` invalid client secret | the secret's *ID* was copied instead of its *Value*, or it expired |
| 403 "המשתמש אינו רשום במערכת" | sign-in worked; no `users` row with that email |
| 403 "החשבון אינו שייך לדומיין" | `ENTRA_ALLOWED_DOMAINS` excludes it |
| 400 "פג תוקף בקשת ההתחברות" | the login sat open past 10 minutes, or cookies are blocked |
| signed out on every deploy | `CITYOS_SESSION_SECRET` unset, or differs per replica |

## What is checked, and why it matters

Running the flow ourselves means we own the verification. On every sign-in:

1. **`state`** matches a value planted in a short-lived signed cookie — without
   it, someone can complete a login *they* started in your browser, and you
   silently act as them.
2. **The code exchange** is server-to-server with the client secret, so no token
   ever reaches the browser. PKCE rides along, making a stolen code useless.
3. **The id_token signature** is verified against the tenant's JWKS (RS256) with
   issuer and audience pinned. An unverified id_token is a JSON blob anyone can
   write.
4. **`nonce`** matches, binding the token to this login attempt — a token minted
   elsewhere cannot be replayed.
5. **`tid`** matches the configured tenant.

The session cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` over https, so
script on the page cannot read it and it does not ride cross-site requests.
`tests/test_entra_sso.py` removes each of these guarantees in turn and asserts
the sign-in is refused.

## What this does not cover

Entra answers *who you are*. *What you may do* is still the app's board and
environment permission model — unchanged by this, and now running against a
verified identity.

Still open: the project/budget/approvals endpoints (`/api/projects/*`,
`/api/kpis`, `/api/approvals`, `/api/change-requests`, `/api/dependencies`,
`/api/steps/*`) require a signed-in user but have no per-object rule, so any
authenticated employee can modify any project. That is a product decision about
which membership model applies, not a mechanical fix.
