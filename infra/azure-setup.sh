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

# The API's session endpoints spend API credit, so they require a shared token
# that only the UI has. Reuse it on re-runs so both apps keep matching.
API_TOKEN="$(az containerapp secret show --name sw-api --resource-group "$RG" \
  --secret-name api-token --query value -o tsv 2>/dev/null || true)"
if [[ -z "$API_TOKEN" ]]; then
  API_TOKEN="$(openssl rand -hex 24)"
  az containerapp secret set --name sw-api --resource-group "$RG" \
    --secrets "api-token=$API_TOKEN" --output none
  az containerapp update --name sw-api --resource-group "$RG" \
    --set-env-vars "SW_API_TOKEN=secretref:api-token" --output none
fi

# The UI calls the API over HTTPS at its own address: express environments
# do not serve plain HTTP, so http://sw-api would only get a redirect.
API_URL="https://$(az containerapp show --name sw-api --resource-group "$RG" \
  --query properties.configuration.ingress.fqdn -o tsv)"

# Streamlit reads its address and port from the environment; passing them as
# --args would be taken by the Azure CLI as its own options.
if ! az containerapp show --name sw-ui --resource-group "$RG" &>/dev/null; then
  az containerapp create --name sw-ui --resource-group "$RG" --environment "$ENV_NAME" \
    --image "$IMAGE" ${registry[@]+"${registry[@]}"} \
    --ingress external --target-port 8501 \
    --min-replicas 0 --max-replicas 1 --cpu 0.5 --memory 1.0Gi \
    --command streamlit --args run src/schichtwechsel/ui/app.py \
    --secrets "access-code=$ACCESS_CODE" "api-token=$API_TOKEN" \
    --env-vars "SW_API_URL=$API_URL" "SW_ACCESS_CODE=secretref:access-code" \
      "SW_API_TOKEN=secretref:api-token" STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
      STREAMLIT_SERVER_PORT=8501 \
    --output none
fi

# GitHub Actions deploys with a federated identity: no password stored anywhere
APP_ID="$(az ad app list --display-name schichtwechsel-deploy --query '[0].appId' -o tsv)"
if [[ -z "$APP_ID" ]]; then
  APP_ID="$(az ad app create --display-name schichtwechsel-deploy --query appId -o tsv)"
  az ad sp create --id "$APP_ID" --output none
fi
# GitHub's token names the repo by name, or by name and numeric ids
# (repo:owner@ownerid/repo@repoid:...), depending on the account. Trust both.
OWNER_ID="$(gh api "repos/$REPO" --jq .owner.id)"
REPO_ID="$(gh api "repos/$REPO" --jq .id)"
for cred in "github-main|repo:$REPO:ref:refs/heads/main" \
  "github-main-ids|repo:$OWNER@$OWNER_ID/${REPO#*/}@$REPO_ID:ref:refs/heads/main"; do
  name="${cred%%|*}"
  subject="${cred#*|}"
  if ! az ad app federated-credential list --id "$APP_ID" --query "[?name=='$name']" -o tsv | grep -q .; then
    az ad app federated-credential create --id "$APP_ID" --parameters "{
      \"name\": \"$name\",
      \"issuer\": \"https://token.actions.githubusercontent.com\",
      \"subject\": \"$subject\",
      \"audiences\": [\"api://AzureADTokenExchange\"]
    }" --output none
  fi
done
az role assignment create --assignee "$APP_ID" --role Contributor \
  --scope "/subscriptions/$SUB/resourceGroups/$RG" --output none 2>/dev/null || true

gh variable set AZURE_CLIENT_ID --body "$APP_ID"
gh variable set AZURE_TENANT_ID --body "$TENANT"
gh variable set AZURE_SUBSCRIPTION_ID --body "$SUB"
gh variable set AZURE_RESOURCE_GROUP --body "$RG"

URL="$(az containerapp show --name sw-ui --resource-group "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
echo "done. UI: https://$URL"
