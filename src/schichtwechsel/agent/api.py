"""HTTP API for the analyst agent.

    uvicorn schichtwechsel.agent.api:app --port 8000

Sessions live in memory and expire after an hour without use. Each session
has its own read-only connection to the warehouse.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from schichtwechsel.agent.executor import VIEW_NOTES, ReadOnlyMart
from schichtwechsel.agent.loop import MODEL, Session

IDLE_SECONDS = 3600
MAX_SESSIONS = 50

app = FastAPI(title="Schichtwechsel analyst", version="0.1.0")
_sessions: dict[str, tuple[Session, float]] = {}
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


@app.post("/sessions")
def new_session() -> dict:
    with _lock:
        _expire()
        if len(_sessions) >= MAX_SESSIONS:
            raise HTTPException(503, "too many open sessions, try again later")
        session = Session(client(), ReadOnlyMart())
        _sessions[session.id] = (session, time.monotonic())
    return {"session_id": session.id}


@app.post("/sessions/{session_id}/ask")
def ask(session_id: str, body: Question) -> dict:
    with _lock:
        entry = _sessions.get(session_id)
        if entry is None:
            raise HTTPException(404, "unknown or expired session")
        _sessions[session_id] = (entry[0], time.monotonic())
    return asdict(entry[0].ask(body.question, body.language))


@app.delete("/sessions/{session_id}")
def close_session(session_id: str) -> dict:
    with _lock:
        entry = _sessions.pop(session_id, None)
    if entry:
        entry[0].mart.close()
    return {"closed": entry is not None}
