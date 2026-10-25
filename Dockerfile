# One image, two processes: the API (default command) and the web UI.
# The warehouse is baked in by the daily build, so the app needs no storage.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# editable, so paths resolve to /app like in the repo
RUN pip install -e ".[app]"

COPY config ./config
COPY .streamlit ./.streamlit
COPY data/warehouse.duckdb ./data/warehouse.duckdb

RUN useradd --create-home --uid 10001 app && chown -R app /app/data
USER app

EXPOSE 8000 8501
CMD ["uvicorn", "schichtwechsel.agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
