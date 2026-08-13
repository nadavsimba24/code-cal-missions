# Entra ID (Azure AD) authentication for CityOS

The app no longer decides who you are from a request parameter. Identity arrives
from the platform, and the backend maps it to a `User` row by email.

## The one setting that matters

Container Apps built-in authentication ("Easy Auth") must be set to **require**
authentication, not to allow unauthenticated access.

When it requires auth, the ingress:

1. redirects anonymous browsers to Entra (with your tenant's MFA policy applied),
2. injects `X-MS-CLIENT-PRINCIPAL` / `X-MS-CLIENT-PRINCIPAL-NAME`, and
3. **strips those headers from inbound client requests** — which is the only
   reason the backend can trust them.

If you set it to "allow unauthenticated access" and let the app handle auth, step 3
stops happening: anyone can send their own `X-MS-CLIENT-PRINCIPAL` header and be
whoever they like. That single toggle is the difference between this working and
this being theatre.

## Enabling it

```bash
RG=<resource-group>
APP=<container-app-name>

# 1. Register the app in Entra (one time). Note the returned appId.
az ad app create --display-name "CityOS" \
  --web-redirect-uris "https://<your-app-host>/.auth/login/aad/callback"

# 2. Turn on Easy Auth with Entra as the provider
az containerapp auth microsoft update -g $RG -n $APP \
  --client-id <appId> \
  --tenant-id <tenantId> \
  --yes

# 3. Require authentication for every request — the critical step
az containerapp auth update -g $RG -n $APP \
  --unauthenticated-client-action RedirectToLoginPage \
  --redirect-provider azureactivedirectory
```

Verify it took effect:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<your-app-host>/api/boards
# 302 (redirect to login) or 401 — never 200
```

MFA is not configured here. It comes from the Conditional Access policy on the
tenant, which is where it belongs.

## Provisioning users

The Entra identity is matched to `users.email`, case-insensitively. A person who
signs in successfully but has no matching row gets a clear 403
("המשתמש אינו רשום במערכת") rather than an empty app.

Two ways to onboard:

- **Explicit (default, recommended for a municipality)** — an admin adds the user
  in the app first, with the same email as their Entra account.
- **Automatic** — set `CITYOS_AUTH_AUTOPROVISION=1` to create a `member` row on
  first sign-in. Only do this if the Entra app registration is already restricted
  to the right group, otherwise anyone in the tenant gets an account.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `CITYOS_AUTH_MODE` | `easyauth` | `dev` trusts an `X-CityOS-User` header. Local only. |
| `CITYOS_AUTH_AUTOPROVISION` | off | Create a user row on first successful sign-in. |
| `CITYOS_CORS_ORIGINS` | empty | Comma-separated extra origins. The SPA is same-origin and needs none. |

`CITYOS_AUTH_MODE` defaults to `easyauth` on purpose: a deployment that was never
configured refuses every request instead of trusting every request. Dev mode lives
in `.env`, which is gitignored and excluded by `.dockerignore`, so it cannot reach
an image.

## Local development

```bash
# .env
CITYOS_AUTH_MODE=dev
```

The login screen reappears as a user picker, and the chosen id is sent as
`X-CityOS-User` on every request. This is the same code path production uses, just
with a different source of identity — so authorization bugs still surface locally.

## What this does and does not cover

Entra answers *who you are*. It does not answer *what you may do* — that is the
app's board/environment permission model, which now runs against a verified
identity instead of a self-declared one.

Still outstanding: the project/budget/approvals endpoints
(`/api/projects/*`, `/api/kpis`, `/api/approvals`, `/api/change-requests`,
`/api/dependencies`, `/api/steps/*`) require a signed-in user but have no
per-object rule, so any authenticated employee can modify any project. Those
objects have no membership model to enforce yet; picking one (by department? by
`Project.manager_id`? by work plan?) is a product decision, not a mechanical fix.
