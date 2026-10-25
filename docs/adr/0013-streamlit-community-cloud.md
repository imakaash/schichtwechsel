# 13. Move hosting from Azure to Streamlit Community Cloud

Date: 2026-10-25
Status: accepted. Supersedes ADR 0012.

## Context

The app ran on Azure Container Apps (ADR 0012): two containers, an image rebuilt daily, OIDC deploys, a token between UI and API. It worked, but for a portfolio project it brought an Azure bill to watch, a long URL, and moving parts that did not add to what the project shows: Azure created an express environment where internal ingress was reachable from outside, settings changes did not restart containers, and the OIDC subject format changed.

## Decision

- Host the web app on Streamlit Community Cloud: free for a public repository, short URL (schichtwechsel.streamlit.app), redeploys on every push.
- Run dashboards and analyst in the app process. The HTTP hop and the UI-to-API token go away; the FastAPI app stays as an optional component.
- The app downloads the warehouse from the `data` release on first start and refreshes it every six hours, swapping the file atomically. A local warehouse is never overwritten.
- The daily job keeps refreshing the data but no longer builds images or deploys. Dockerfile, the Azure setup script and the Azure workflow steps are removed.
- Spend limits move into a shared module used by the app and the optional API.
- The app has its own folder with a lean `requirements.txt`, because Community Cloud would otherwise pick the conda `environment.yml` at the root.

## Consequences

- No hosting cost. The Anthropic key is the only thing that can cost money, capped per day.
- The app sleeps after about 12 hours without visitors and takes about half a minute to wake.
- Less infrastructure to show. ADR 0012 records the Azure deployment that ran, what it taught, and why it was retired.
