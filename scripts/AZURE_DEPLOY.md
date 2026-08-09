# Deploying to Azure Container Apps

The app ships as a container ([`Dockerfile`](../Dockerfile)) — a FastAPI backend
that also serves the single-file frontend, listening on `$PORT` / `0.0.0.0`.

Production URL:
`https://missionspoccontainer.kindwave-29864c84.westeurope.azurecontainerapps.io/`

## Why this is the safe way

- **Revisions** — every deploy creates a new Container Apps revision. The old one
  stays until the new one is healthy, so rollback is one command.
- **Gate first** — the same `./run_tests.sh` (116 tests + SAST + secrets) that
  guards Vercel runs before any image is built.
- **Immutable tags** — images are tagged with the git short-SHA, never just
  `latest`, so "which revision is which" is unambiguous.
- **Auto rollback** — if the new revision fails `/api/status`, the pipeline
  redeploys the previous image automatically.
- **Secrets stay in Azure** — `DATABASE_URL` etc. live as Container App secrets/env,
  never in the image. `.dockerignore` already keeps `.env` and `*.db` out.
  `az containerapp update --image` keeps the app's existing env/secrets.

## Two ways to deploy

### A. Commit-triggered CI (recommended)
`.github/workflows/azure-deploy.yml` deploys on every push to `main`
(or manually via **Actions → Deploy to Azure Container Apps → Run workflow**).

### B. Manual, from your machine
```bash
export AZURE_RESOURCE_GROUP=<rg>
export AZURE_ACR_NAME=<acr>              # the registry NAME, not the login server
export AZURE_CONTAINERAPP_NAME=missionspoccontainer
./scripts/azure-deploy.sh
```
Requires `az login`. Docker is **not** needed — the image builds in ACR.

## One-time setup

### 0. Find your resource group / registry (if unsure)
```bash
brew install azure-cli          # macOS; then:
az login
# which RG is the container app in, and what's its current image/registry?
az containerapp list -o table
az containerapp show -n missionspoccontainer -g <rg> \
  --query "{rg:resourceGroup, image:properties.template.containers[0].image}" -o jsonc
az acr list -o table            # your registries (ACR name = the part before .azurecr.io)
```
If there is **no** ACR yet, create one and grant the app pull access:
```bash
az acr create -g <rg> -n <acr> --sku Basic
```

### 1. Repo configuration (Settings → Secrets and variables → Actions)
**Variables** (not secret):
| name | value |
|------|-------|
| `AZURE_RESOURCE_GROUP` | your RG |
| `AZURE_ACR_NAME` | your ACR name |
| `AZURE_CONTAINERAPP_NAME` | `missionspoccontainer` |
| `AZURE_CONTAINERAPP_URL` | `https://missionspoccontainer.kindwave-29864c84.westeurope.azurecontainerapps.io` |

**Secrets** (OIDC — recommended, no stored password):
`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`.

### 2. Azure identity for GitHub (OIDC federation)
```bash
# create an app registration + service principal
az ad app create --display-name "github-missions-deploy"
APP_ID=$(az ad app list --display-name "github-missions-deploy" --query "[0].appId" -o tsv)
az ad sp create --id "$APP_ID"

# federated credential: trust pushes to main of this repo
az ad app federated-credential create --id "$APP_ID" --parameters '{
  "name": "github-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:Mashcal-Projects/code-cal-missions:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'

# least-privilege roles: push to ACR + manage the container app
SUB=$(az account show --query id -o tsv)
az role assignment create --assignee "$APP_ID" --role AcrPush \
  --scope "/subscriptions/$SUB/resourceGroups/<rg>/providers/Microsoft.ContainerRegistry/registries/<acr>"
az role assignment create --assignee "$APP_ID" --role "Contributor" \
  --scope "/subscriptions/$SUB/resourceGroups/<rg>/providers/Microsoft.App/containerApps/missionspoccontainer"
```
Put `$APP_ID` in `AZURE_CLIENT_ID`, `az account show --query tenantId` in
`AZURE_TENANT_ID`, and `$SUB` in `AZURE_SUBSCRIPTION_ID`.

> Simpler alternative to OIDC: create a client-secret service principal and store
> the JSON as a single `AZURE_CREDENTIALS` secret, then swap the login step to
> `azure/login@v2` with `creds: ${{ secrets.AZURE_CREDENTIALS }}`. Works, but is a
> long-lived password — prefer OIDC.

## Rollback (manual)
```bash
# list revisions, then send all traffic to a known-good one (multi-revision mode)…
az containerapp revision list -n missionspoccontainer -g <rg> -o table
# …or, in single-revision mode, just redeploy the previous image:
az containerapp update -n missionspoccontainer -g <rg> --image <acr>.azurecr.io/missions:<old-sha>
```

## Runtime env the container needs (set on the Container App, once)
- `DATABASE_URL` — the same Neon Postgres URL the app already uses (shared state;
  uploads persist in the DB). Store it as a Container App **secret**.
- `PORT` — Container Apps sets this; `main.py` already honors it.
