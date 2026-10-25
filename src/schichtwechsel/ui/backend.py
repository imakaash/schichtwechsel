"""Data and analyst for the web app, in the same process.

On Streamlit Community Cloud the repository has no data: the warehouse is
downloaded from the `data` release on first use and refreshed every few
hours, after the daily job has replaced it. Locally, an existing
data/warehouse.duckdb is used as is and never overwritten.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path

import httpx
import pandas as pd
import streamlit as st

from schichtwechsel.agent.dashboard import QUERIES
from schichtwechsel.agent.executor import ReadOnlyMart
from schichtwechsel.agent.limits import LimitReached, SpendLimiter
from schichtwechsel.agent.loop import Session
from schichtwechsel.config import ROOT, WAREHOUSE

DATA_URL = "https://github.com/imakaash/schichtwechsel/releases/download/data/warehouse.duckdb"
REFRESH_SECONDS = 6 * 3600
MARKER = WAREHOUSE.with_suffix(".downloaded")  # present only for a downloaded copy

__all__ = ["LimitReached", "ask", "dataset", "new_conversation", "secret"]

_download_lock = threading.Lock()


def secret(name: str) -> str | None:
    """Environment first, then Streamlit's secrets store (Community Cloud)."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        value = st.secrets.get(name)
    except Exception:  # no secrets file locally
        return None
    return str(value) if value else None


def _download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp:
        resp.raise_for_status()
        with partial.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
    # atomic swap: open connections keep reading the old file until they close
    os.replace(partial, target)
    MARKER.write_text(str(time.time()))


def ensure_warehouse(url: str | None = None, now: float | None = None) -> Path:
    """Make sure a warehouse is there; refresh a downloaded one when it is stale."""
    url = url or secret("SW_DATA_URL") or DATA_URL
    now = now or time.time()
    with _download_lock:
        if not WAREHOUSE.exists():
            _download(url, WAREHOUSE)
        elif MARKER.exists() and now - float(MARKER.read_text() or 0) > REFRESH_SECONDS:
            # if the refresh fails, keep serving the copy we have
            with contextlib.suppress(httpx.HTTPError):
                _download(url, WAREHOUSE)
    return WAREHOUSE


@st.cache_data(ttl=600, show_spinner=False)
def dataset(name: str) -> pd.DataFrame:
    mart = ReadOnlyMart(ensure_warehouse())
    try:
        body = mart.fetch(QUERIES[name])
    finally:
        mart.close()
    return pd.DataFrame(body["rows"], columns=body["columns"])


@st.cache_resource
def _client():
    import anthropic
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    key = secret("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


@st.cache_resource
def _limiter() -> SpendLimiter:
    budget = secret("SW_DAILY_BUDGET_USD")
    questions = secret("SW_MAX_QUESTIONS")
    return SpendLimiter(
        float(budget) if budget else None,
        int(questions) if questions else None,
    )


def new_conversation() -> Session:
    return Session(_client(), ReadOnlyMart(ensure_warehouse()))


def ask(conversation: Session, question: str, language: str) -> dict:
    limiter = _limiter()
    limiter.admit(conversation.id)
    answer = conversation.ask(question, language)
    limiter.record(answer.cost_usd)
    return asdict(answer)
