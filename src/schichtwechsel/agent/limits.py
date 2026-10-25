"""Spend limits for the analyst, shared by the web app and the optional API.

A public page could otherwise spend the API key without limit. Counters
live in memory: they reset when the process restarts, which is accepted.
"""

from __future__ import annotations

import os
import threading
from datetime import date


class LimitReached(RuntimeError):
    """Daily budget used up, or the conversation hit its question limit."""


class SpendLimiter:
    def __init__(self, daily_budget_usd: float | None = None, max_questions: int | None = None):
        self.daily_budget_usd = (
            daily_budget_usd
            if daily_budget_usd is not None
            else float(os.environ.get("SW_DAILY_BUDGET_USD", "2.0"))
        )
        self.max_questions = (
            max_questions
            if max_questions is not None
            else int(os.environ.get("SW_MAX_QUESTIONS", "30"))
        )
        self._spent: dict[date, float] = {}
        self._asked: dict[str, int] = {}
        self._lock = threading.Lock()

    def admit(self, conversation: str) -> None:
        """Reserve one question for this conversation, or raise LimitReached."""
        with self._lock:
            if self._spent.get(date.today(), 0.0) >= self.daily_budget_usd:
                raise LimitReached("daily budget used up")
            if self._asked.get(conversation, 0) >= self.max_questions:
                raise LimitReached("question limit for this conversation reached")
            self._asked[conversation] = self._asked.get(conversation, 0) + 1

    def record(self, cost_usd: float) -> None:
        with self._lock:
            self._spent[date.today()] = self._spent.get(date.today(), 0.0) + cost_usd

    def spent_today(self) -> float:
        with self._lock:
            return self._spent.get(date.today(), 0.0)
