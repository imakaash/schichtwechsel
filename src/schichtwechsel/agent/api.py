"""Optional HTTP API for the analyst agent and the dashboard data.

The web app does not need it (it calls the same code in-process); it is
here for other clients and local use.

    uvicorn schichtwechsel.agent.api:app --port 8000

Sessions live in memory and expire after an hour without use. Each session
has its own read-only connection to the warehouse.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from dataclasses import asdict
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from schichtwechsel.agent.dashboard import QUERIES
from schichtwechsel.agent.executor import VIEW_NOTES, ReadOnlyMart
from schichtwechsel.agent.limits import LimitReached, SpendLimiter
from schichtwechsel.agent.loop import MODEL, Session

IDLE_SECONDS = 3600
MAX_SESSIONS = 50
# Shared secret between UI and API for the endpoints that spend API credit.
# Network rules alone are not relied on; unset means local development.
API_TOKEN = os.environ.get("SW_API_TOKEN", "")


def require_token(x_sw_token: str = Header(default="")) -> None:
    if API_TOKEN and not hmac.compare_digest(x_sw_token.encode(), API_TOKEN.encode()):
        raise HTTPException(401, "missing or wrong token")


app = FastAPI(title="Schichtwechsel analyst", version="0.1.0")
_sessions: dict[str, tuple[Session, float]] = {}
limiter = SpendLimiter()
_lock = threading.Lock()
_client = None


def client():
    global _client
    if _client is None:
        import anthropic
        from dotenv import load_dotenv

        from schichtwechsel.config import ROOT

        load_dotenv(ROOT / ".env")
        _client = anthropic.Anthropic()
    return _client


def _expire() -> None:
    now = time.monotonic()
    for sid, (session, seen) in list(_sessions.items()):
        if now - seen > IDLE_SECONDS:
            session.mart.close()
            del _sessions[sid]


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: Literal["de", "en"] = "de"


@app.get("/health")
def health() -> dict:
    mart = ReadOnlyMart()
    try:
        views = len(mart.views)
    finally:
        mart.close()
    return {"status": "ok", "model": MODEL, "views": views}


@app.get("/views")
def views() -> dict:
    return VIEW_NOTES


@app.get("/data/{name}")
def data(name: str) -> dict:
    """Dashboard data by name. The client cannot send SQL."""
    if name not in QUERIES:
        raise HTTPException(404, f"unknown dataset; available: {', '.join(sorted(QUERIES))}")
    mart = ReadOnlyMart()
    try:
        return mart.fetch(QUERIES[name])
    finally:
        mart.close()


@app.post("/sessions", dependencies=[Depends(require_token)])
def new_session() -> dict:
    with _lock:
        _expire()
        if len(_sessions) >= MAX_SESSIONS:
            raise HTTPException(503, "too many open sessions, try again later")
        session = Session(client(), ReadOnlyMart())
        _sessions[session.id] = (session, time.monotonic())
    return {"session_id": session.id}


@app.post("/sessions/{session_id}/ask", dependencies=[Depends(require_token)])
def ask(session_id: str, body: Question) -> dict:
    with _lock:
        entry = _sessions.get(session_id)
        if entry is None:
            raise HTTPException(404, "unknown or expired session")
        _sessions[session_id] = (entry[0], time.monotonic())
    try:
        limiter.admit(session_id)
    except LimitReached as exc:
        raise HTTPException(429, str(exc)) from exc
    answer = entry[0].ask(body.question, body.language)
    limiter.record(answer.cost_usd)
    return asdict(answer)


@app.delete("/sessions/{session_id}", dependencies=[Depends(require_token)])
def close_session(session_id: str) -> dict:
    with _lock:
        entry = _sessions.pop(session_id, None)
    if entry:
        entry[0].mart.close()
    return {"closed": entry is not None}
