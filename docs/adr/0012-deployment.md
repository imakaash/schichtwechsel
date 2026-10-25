# 12. One image on Azure Container Apps, data baked in, state in a GitHub release

Date: 2026-10-25
Status: accepted

## Context

The app has an API (agent and dashboard data) and a web UI. Data changes once a day. The budget is a free Azure account and the free GitHub Actions minutes of a private repository.

## Decision

- **One image, two container apps.** The API runs internal-only; the UI is public and reaches the API at `http://sw-api` inside the environment. Both scale to zero.
- **The warehouse is part of the image.** It is about 20 MB. The daily build copies it in, so the app needs no storage account and every deployed version carries exactly the data it was tested with.
- **Daily state lives in a GitHub release** named `data`: the job downloads yesterday's warehouse, adds today's snapshot, uploads it again, and adds the day's raw responses as a dated archive.
- **The daily job never waits for Claude.** It collects yesterday's extraction batch and submits today's. A run takes about 20 minutes, around 600 minutes a month.
- **Order of steps:** save the data first, then run `sw check`. A failed check keeps the data but stops the build and deploy.
- **Deploy with OIDC.** GitHub Actions logs in to Azure through a federated credential limited to the main branch; no Azure password is stored.
- **Cost guards for a public UI:** access code on the analyst page, daily spend cap and per-conversation question cap in the API.
- **Logs off** in the Container Apps environment, to avoid Log Analytics charges. The agent's own JSONL log stays inside the container.
- **Dependencies split** into `ml`, `app` and `dev` extras, so the image does not ship scikit-learn and SHAP.

## Consequences

- The warehouse grows by roughly 1 to 2 MB a day. Past a few hundred MB, move it to Azure Blob Storage and mount it, as planned in step 3 of the plan.
- The image registry belongs to a private repository, so Azure pulls with a read-only GitHub token. Making the repository public later removes that step.
- Agent logs and the spend counter are lost when a container restarts. Acceptable for a portfolio app; production use would send logs to a store.
- The synthetic HR data and models are not regenerated daily; the fictional chain stays stable while the competitor data moves.

## What the first deployment showed (2026-10-25)

- Azure created an *express* Container Apps environment. It does not offer plain HTTP on ingress, and the API answered from the internet despite `external: false`. Network isolation was therefore not relied on: the endpoints that spend API credit require a token only the UI holds, and the UI calls the API over HTTPS.
- Updating a container app's settings in an express environment did not restart the running container; the new settings applied with the next image deploy.
- GitHub presented an OIDC subject with numeric ids (`repo:owner@id/repo@id:ref:refs/heads/main`). Azure trusts both that and the name-only form.
- Student subscriptions allow only some regions; the app runs in France Central.
