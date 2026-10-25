"""HTTP client for the API. The UI never opens the database itself."""

from __future__ import annotations

import os

import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("SW_API_URL", "http://localhost:8000").rstrip("/")
HEADERS = {"X-SW-Token": os.environ.get("SW_API_TOKEN", "")}


class ApiError(RuntimeError):
    pass


class LimitReached(RuntimeError):
    """Daily budget or per-conversation question limit."""


def _get(path: str) -> dict:
    try:
        resp = httpx.get(f"{API_URL}{path}", timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiError(str(exc)) from exc
    return resp.json()


@st.cache_data(ttl=600, show_spinner=False)
def dataset(name: str) -> pd.DataFrame:
    body = _get(f"/data/{name}")
    return pd.DataFrame(body["rows"], columns=body["columns"])


def new_session() -> str:
    resp = httpx.post(f"{API_URL}/sessions", headers=HEADERS, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()["session_id"]


def ask(session_id: str, question: str, language: str) -> dict:
    resp = httpx.post(
        f"{API_URL}/sessions/{session_id}/ask",
        json={"question": question, "language": language},
        headers=HEADERS,
        timeout=180,
        follow_redirects=True,
    )
    if resp.status_code == 404:
        raise KeyError("session expired")
    if resp.status_code == 429:
        raise LimitReached(resp.json().get("detail", ""))
    resp.raise_for_status()
    return resp.json()
