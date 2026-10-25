#!/usr/bin/env bash
# One-time Azure setup for Schichtwechsel. Safe to re-run.
#
# Needs: az (logged in with `az login`), gh (logged in), and these variables:
#   ACCESS_CODE    code that unlocks the analyst page in the public UI
#   GHCR_PAT       only if the image is private: GitHub token with read:packages
# ANTHROPIC_API_KEY is read from .env if not set.
#
# Creates: resource group, Container Apps environment (logs off, no Log
# Analytics cost), the internal API app and the public UI app (both scale to
# zero), and an OIDC trust so GitHub Actions can deploy without a stored secret.
set -euo pipefail

RG="${RG:-schichtwechsel-rg}"
LOCATION="${LOCATION:-francecentral}"
ENV_NAME="${ENV_NAME:-schichtwechsel-env}"
REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
OWNER="${REPO%%/*}"
IMAGE="ghcr.io/$(echo "$REPO" | tr "[:upper:]" "[:lower:]"):latest"

: "${ACCESS_CODE:?set ACCESS_CODE (unlocks the analyst page)}"
if [[ -z "${ANTHROPIC_API_KEY:-}" && -f .env ]]; then
  # strip surrounding quotes, as python-dotenv does when the app reads .env
  ANTHROPIC_API_KEY="$(grep -E '^ANTHROPIC_API_KEY=' .env | cut -d= -f2- | sed -E "s/^[\"']//; s/[\"']$//")"
fi
: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY or put it in .env}"

SUB="$(az account show --query id -o tsv)"
TENANT="$(az account show --query tenantId -o tsv)"
echo "subscription $SUB, resource group $RG in $LOCATION, image $IMAGE"

az extension add --name containerapp --upgrade --only-show-errors
az provider register --namespace Microsoft.App --wait
az group create --name "$RG" --location "$LOCATION" --output none

if ! az containerapp env show --name "$ENV_NAME" --resource-group "$RG" &>/dev/null; then
  az containerapp env create --name "$ENV_NAME" --resource-group "$RG" --location "$LOCATION" \
    --logs-destination none --output none
fi

# a public image needs no credentials; a private one needs GHCR_PAT
registry=()
if [[ -n "${GHCR_PAT:-}" ]]; then
  registry=(--registry-server ghcr.io --registry-username "$OWNER" --registry-password "$GHCR_PAT")
fi

if ! az containerapp show --name sw-api --resource-group "$RG" &>/dev/null; then
  az containerapp create --name sw-api --resource-group "$RG" --environment "$ENV_NAME" \
    --image "$IMAGE" ${registry[@]+"${registry[@]}"} \
    --ingress internal --target-port 8000 \
    --min-replicas 0 --max-replicas 1 --cpu 0.5 --memory 1.0Gi \
    --secrets "anthropic-key=$ANTHROPIC_API_KEY" \
    --env-vars "ANTHROPIC_API_KEY=secretref:anthropic-key" SW_DAILY_BUDGET_USD=2 SW_MAX_QUESTIONS=30 \
    --output none
fi

if ! az containerapp show --name sw-ui --resource-group "$RG" &>/dev/null; then
  az containerapp create --name sw-ui --resource-group "$RG" --environment "$ENV_NAME" \
    --image "$IMAGE" ${registry[@]+"${registry[@]}"} \
    --ingress external --target-port 8501 \
    --min-replicas 0 --max-replicas 1 --cpu 0.5 --memory 1.0Gi \
    --command streamlit \
    --args run src/schichtwechsel/ui/app.py --server.address 0.0.0.0 --server.port 8501 \
    --secrets "access-code=$ACCESS_CODE" \
    --env-vars SW_API_URL=http://sw-api "SW_ACCESS_CODE=secretref:access-code" \
    --output none
fi

# GitHub Actions deploys with a federated identity: no password stored anywhere
APP_ID="$(az ad app list --display-name schichtwechsel-deploy --query '[0].appId' -o tsv)"
if [[ -z "$APP_ID" ]]; then
  APP_ID="$(az ad app create --display-name schichtwechsel-deploy --query appId -o tsv)"
  az ad sp create --id "$APP_ID" --output none
fi
if ! az ad app federated-credential list --id "$APP_ID" --query "[?name=='github-main']" -o tsv | grep -q .; then
  az ad app federated-credential create --id "$APP_ID" --parameters "{
    \"name\": \"github-main\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:$REPO:ref:refs/heads/main\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }" --output none
fi
az role assignment create --assignee "$APP_ID" --role Contributor \
  --scope "/subscriptions/$SUB/resourceGroups/$RG" --output none 2>/dev/null || true

gh variable set AZURE_CLIENT_ID --body "$APP_ID"
gh variable set AZURE_TENANT_ID --body "$TENANT"
gh variable set AZURE_SUBSCRIPTION_ID --body "$SUB"
gh variable set AZURE_RESOURCE_GROUP --body "$RG"

URL="$(az containerapp show --name sw-ui --resource-group "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
echo "done. UI: https://$URL"
