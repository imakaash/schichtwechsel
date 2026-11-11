# Deployment

The web app runs on Streamlit Community Cloud at **https://schichtwechsel.streamlit.app**, free. The data is a fixed state from the last snapshot on 2026-11-05; daily collection has ended (ADR 0014). See ADR 0013 for the hosting, and ADR 0012 for the earlier Azure setup.

## How it fits together

- **Data.** The warehouse (DuckDB, about 25 MB) lives in the GitHub release `data`. It was refreshed daily from 2026-10-25 to 2026-11-05 and is no longer updated. To refresh it by hand, run `sw snapshot`, `sw details`, `sw extract submit` and `collect` locally and upload the file with `gh release upload data data/warehouse.duckdb --clobber`.
- **App.** Entry point `app/streamlit_app.py`, dependencies `app/requirements.txt`. On first start the app downloads the warehouse from the release and refreshes it every six hours. Dashboards and the analyst run in the same process; there is no separate API.
- **Optional API.** `src/schichtwechsel/agent/api.py` serves the same data and analyst over HTTP for local use or other clients. The web app does not need it.

## One-time setup on Streamlit Community Cloud

1. Sign in at share.streamlit.io with GitHub.
2. Create app > from a GitHub repository:
   - Repository `imakaash/schichtwechsel`, branch `main`
   - Main file path `app/streamlit_app.py`
   - App URL `schichtwechsel` (gives schichtwechsel.streamlit.app if free)
3. Advanced settings: Python 3.12, and in Secrets:

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   SW_ACCESS_CODE = "your-code"
   ```

4. Deploy. The first start takes a few minutes (dependencies, then the data download).

Every push to `main` redeploys the app. To change a secret, edit it in the app's settings; the app restarts.

## Secrets

| Where | Name | Purpose |
|---|---|---|
| Streamlit secrets | `ANTHROPIC_API_KEY` | the analyst |
| Streamlit secrets | `SW_ACCESS_CODE` | unlocks the analyst page |
| Streamlit secrets, optional | `SW_DAILY_BUDGET_USD`, `SW_MAX_QUESTIONS` | change the caps (defaults 2 USD and 30) |

## Cost guards

- The analyst is switched off in code (`ASSISTANT_ON` in `src/schichtwechsel/ui/pages.py`, ADR 0015). When on, it is locked behind the access code; the dashboards are public.
- The app refuses new questions once the day's spend reaches the budget and caps a conversation at 30 questions. Both counters reset when the app restarts.

## Limits

- The app sleeps after about 12 hours without visitors; the next visitor wakes it, which takes about half a minute.
- Community Cloud gives roughly 1 GB of memory, enough for this data.

## Running locally

```bash
streamlit run app/streamlit_app.py
```

Uses `data/warehouse.duckdb` if it exists (never overwritten), otherwise downloads it. The key comes from `.env`.
