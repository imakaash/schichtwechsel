# Deployment

The app runs on Azure Container Apps: an internal API container and a public UI container from the same image, both scaling to zero. A daily GitHub Actions job refreshes the data, rebuilds the image and deploys it. See ADR 0012 for the reasoning.

## One-time setup

1. **Azure account.** A free standard account or Azure for Students is enough. The Container Apps free grant covers this app at low traffic. Student subscriptions restrict regions by policy (check with `az policy assignment list`); the script defaults to `francecentral`, which is allowed there and offers Container Apps. Override with `LOCATION=...`.
2. **Azure CLI.** `brew install azure-cli`, then `az login`.
3. **GitHub token, only for a private image.** With a public repository the image is public and Azure pulls it without credentials. For a private one, create a classic token at github.com/settings/tokens with only the `read:packages` scope and pass it as `GHCR_PAT`.
4. **First image.** Run the daily workflow once (Actions > daily > Run workflow). Without Azure variables it builds and pushes the image and skips the deploy.
5. **Azure resources.** From the repo root:

   ```bash
   ACCESS_CODE=<code for the analyst page> ./infra/azure-setup.sh
   ```

   It creates the resource group, the Container Apps environment, both apps and the OIDC trust, and sets the GitHub variables the workflow needs. It prints the public URL.

From then on, the daily workflow deploys every morning.

## Secrets

| Where | Name | Purpose |
|---|---|---|
| GitHub secret | `ANTHROPIC_API_KEY` | extraction in the daily job, weekly evals |
| Container App `sw-api` secret | `anthropic-key` | the analyst agent |
| Container App `sw-ui` secret | `access-code` | unlocks the analyst page |
| Both container apps, secret | `api-token` | UI to API authentication for the session endpoints |
| GitHub variables | `AZURE_*` | OIDC login, no password stored |

## Cost guards

- The API's session endpoints (the ones that spend API credit) require a shared token, `SW_API_TOKEN`, which only the UI has. The setup script generates it. This does not rely on the network: on a Container Apps environment without a VNet, the API answered from the internet even with `external: false` ingress, so network isolation alone was not enough.

- The API refuses new questions once the day's spend reaches `SW_DAILY_BUDGET_USD` (2 USD) and caps a conversation at `SW_MAX_QUESTIONS` (30). Both reset when the container restarts.
- The analyst page is locked behind the access code; the dashboards are public.
- Both apps scale to zero; the first request after a pause takes a few seconds longer.

## Running locally

```bash
uvicorn schichtwechsel.agent.api:app --port 8000
streamlit run src/schichtwechsel/ui/app.py
```
