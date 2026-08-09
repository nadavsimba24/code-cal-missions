#!/usr/bin/env bash
# Manual/local equivalent of .github/workflows/azure-deploy.yml.
# Same safe flow: gate → build (immutable SHA tag) → new revision → health check
# → auto roll back to the previous image on failure.
#
# Usage:
#   export AZURE_RESOURCE_GROUP=... AZURE_ACR_NAME=... AZURE_CONTAINERAPP_NAME=...
#   [export AZURE_CONTAINERAPP_URL=https://...]   # defaults to the known POC URL
#   [SKIP_TESTS=1]  ./scripts/azure-deploy.sh
#
# Requires: az CLI (logged in via `az login`), git. Docker is NOT needed —
# the image is built in ACR.
set -euo pipefail
cd "$(dirname "$0")/.."

RG="${AZURE_RESOURCE_GROUP:-}"
ACR="${AZURE_ACR_NAME:-}"
APP="${AZURE_CONTAINERAPP_NAME:-}"
APP_URL="${AZURE_CONTAINERAPP_URL:-https://missionspoccontainer.kindwave-29864c84.westeurope.azurecontainerapps.io}"

for v in RG ACR APP; do
  if [ -z "${!v}" ]; then echo "❌ set AZURE_${v/RG/RESOURCE_GROUP} (missing $v)"; exit 1; fi
done
command -v az >/dev/null || { echo "❌ az CLI not installed — see scripts/AZURE_DEPLOY.md"; exit 1; }
az account show >/dev/null 2>&1 || { echo "❌ not logged in — run: az login"; exit 1; }

# 1) gate (tests + SAST + secrets) — same as pre-Vercel deploys
if [ "${SKIP_TESTS:-0}" != "1" ]; then
  echo "── gate ──"; ./run_tests.sh
fi

SHA="$(git rev-parse --short HEAD)"
IMAGE="${ACR}.azurecr.io/missions:${SHA}"

# 2) remember the current image so we can roll back
PREV="$(az containerapp show -n "$APP" -g "$RG" \
        --query 'properties.template.containers[0].image' -o tsv || true)"
echo "current image: ${PREV:-<none>}"

# 3) build in ACR (immutable SHA tag + moving latest)
echo "── az acr build → ${IMAGE} ──"
az acr build -r "$ACR" -t "missions:${SHA}" -t "missions:latest" .

# 4) roll out a new revision
echo "── deploy new revision ──"
az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" >/dev/null

# 5) health check, roll back on failure
echo "── health check ${APP_URL}/api/status ──"
ok=0
for i in $(seq 1 12); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "${APP_URL}/api/status" || echo 000)"
  echo "  attempt $i → HTTP $code"
  if [ "$code" = "200" ]; then ok=1; break; fi
  sleep 10
done

if [ "$ok" = "1" ]; then
  echo "✅ deployed & healthy: $IMAGE"
else
  echo "❌ health check failed."
  if [ -n "$PREV" ]; then
    echo "↩︎  rolling back to $PREV"
    az containerapp update -n "$APP" -g "$RG" --image "$PREV" >/dev/null
    echo "rolled back."
  fi
  exit 1
fi
