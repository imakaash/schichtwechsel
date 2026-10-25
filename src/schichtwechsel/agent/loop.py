"""The analyst agent: a plain tool-use loop on the Anthropic SDK.

No framework on purpose: every step is visible here. The conversation is
append-only (thinking blocks are passed back unchanged and nothing earlier
is edited), each final answer is checked for grounding and language, and a
failed check gets one retry with the reason before the answer is replaced
by a safe fallback.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from schichtwechsel.agent.checks import language_of, ungrounded
from schichtwechsel.agent.executor import QueryResult, ReadOnlyMart
from schichtwechsel.agent.prompt import TOOLS, system_blocks
from schichtwechsel.config import DATA_DIR

MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
MAX_STEPS = 10
FALLBACK_BETA = "server-side-fallback-2026-07-01"
LOG_FILE = DATA_DIR / "logs" / "agent.jsonl"

# USD per million tokens for claude-sonnet-5-5
PRICE = {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.2}

FALLBACK_TEXT = {
    "de": "Ich konnte keine Antwort erstellen, deren Zahlen sich vollständig aus den Abfragen "
    "belegen lassen. Die Abfrageergebnisse stehen unten.",
    "en": "I could not write an answer whose figures are all backed by the query results. "
    "The query results are below.",
}
REFUSAL_TEXT = {
    "de": "Diese Anfrage kann ich nicht bearbeiten.",
    "en": "I can't help with this request.",
}

log = logging.getLogger(__name__)
_log_lock = threading.Lock()  # sessions in parallel share the log file


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    requests: int = 0

    def add(self, usage: Any) -> None:
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.requests += 1

    @property
    def cost_usd(self) -> float:
        return round(
            (
                self.input_tokens * PRICE["input"]
                + self.output_tokens * PRICE["output"]
                + self.cache_write_tokens * PRICE["cache_write"]
                + self.cache_read_tokens * PRICE["cache_read"]
            )
            / 1e6,
            5,
        )


@dataclass
class Answer:
    text: str
    language: str
    queries: list[dict] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)
    declined: str | None = None
    grounded: bool = True
    checks: list[str] = field(default_factory=list)
    refused: bool = False
    steps: int = 0
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    seconds: float = 0.0


class Session:
    """One conversation. Keeps the message history and every query result."""

    def __init__(self, client: Any, mart: ReadOnlyMart, log_file: Path | None = LOG_FILE) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.client = client
        self.mart = mart
        self.catalog = mart.catalog()
        self.messages: list[dict[str, Any]] = []
        self.results: dict[str, QueryResult] = {}
        self.log_file = log_file

    # tools -------------------------------------------------------------

    def _run_tool(self, name: str, args: dict, turn: dict) -> tuple[str, bool]:
        if name == "run_sql":
            query_id = f"q{len(self.results) + 1}"
            result = self.mart.run(query_id, args.get("sql", ""), args.get("purpose", ""))
            self.results[query_id] = result
            turn["queries"].append(query_id)
            return json.dumps(result.for_model(), ensure_ascii=False), result.error is not None
        if name == "make_chart":
            result = self.results.get(args.get("query_id", ""))
            if result is None or result.error:
                return "unknown query_id; run the query first", True
            needed = [args.get("x"), args.get("y")] + (
                [args["series"]] if args.get("series") else []
            )
            missing = [c for c in needed if c not in result.columns]
            if missing:
                return f"columns not in {result.query_id}: {', '.join(missing)}", True
            chart = {**args, "chart_id": f"c{len(turn['charts']) + 1}"}
            turn["charts"].append(chart)
            return json.dumps({"chart_id": chart["chart_id"]}), False
        if name == "decline":
            turn["declined"] = args.get("reason")
            return "recorded; now tell the user briefly", False
        return f"unknown tool {name}", True

    # one question --------------------------------------------------------

    def _create(self, language: str) -> Any:
        return self.client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=system_blocks(self.catalog, language),
            tools=TOOLS,
            messages=self.messages,
            output_config={"effort": EFFORT},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )

    def ask(self, question: str, language: str = "de") -> Answer:
        started = time.monotonic()
        usage = Usage()
        turn: dict[str, Any] = {"queries": [], "charts": [], "declined": None}
        self.messages.append({"role": "user", "content": question})
        retried = False
        answer: Answer | None = None

        for step in range(1, MAX_STEPS + 1):
            response = self._create(language)
            usage.add(response.usage)
            if response.stop_reason == "refusal":
                answer = Answer(REFUSAL_TEXT[language], language, refused=True, steps=step)
                break
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    content, is_error = self._run_tool(block.name, block.input, turn)
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": content,
                            "is_error": is_error,
                        }
                    )
                self.messages.append({"role": "user", "content": results})
                continue

            text = "\n".join(b.text for b in response.content if b.type == "text").strip()
            problems = self._check(text, question, language)
            if problems and not retried:
                retried = True
                self.messages.append(
                    {
                        "role": "user",
                        "content": "Automatic check, not from the user: "
                        + " ".join(problems)
                        + " Fix this and write the answer again.",
                    }
                )
                continue
            answer = Answer(text, language, checks=problems, steps=step)
            if problems:
                answer.grounded = False
                answer.text = FALLBACK_TEXT[language]
            break
        else:
            answer = Answer(FALLBACK_TEXT[language], language, grounded=False, steps=MAX_STEPS)
            answer.checks.append(f"stopped after {MAX_STEPS} steps")

        answer.queries = [asdict(self.results[q]) for q in turn["queries"]]
        answer.charts = [self._chart_data(c) for c in turn["charts"]]
        answer.declined = turn["declined"]
        answer.usage = asdict(usage)
        answer.cost_usd = usage.cost_usd
        answer.seconds = round(time.monotonic() - started, 2)
        self._log(question, answer)
        return answer

    def _check(self, text: str, question: str, language: str) -> list[str]:
        problems = []
        if not text:
            problems.append("The answer is empty.")
        missing = ungrounded(text, (r.for_model() for r in self.results.values()), question)
        if missing:
            problems.append(
                "These figures appear in no query result: "
                + ", ".join(missing)
                + ". Use only figures from query results; compute derived figures in SQL."
            )
        found = language_of(text)
        if found and found != language:
            problems.append(f"The answer must be in {'German' if language == 'de' else 'English'}.")
        return problems

    def _chart_data(self, chart: dict) -> dict:
        result = self.results[chart["query_id"]]
        cols = [chart["x"], chart["y"]] + ([chart["series"]] if chart.get("series") else [])
        idx = [result.columns.index(c) for c in cols]
        return {**chart, "columns": cols, "rows": [[row[i] for i in idx] for row in result.rows]}

    def _log(self, question: str, answer: Answer) -> None:
        if self.log_file is None:
            return
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "session": self.id,
            "model": MODEL,
            "question": question,
            **{k: v for k, v in asdict(answer).items() if k != "charts"},
        }
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with _log_lock, self.log_file.open("a", encoding="utf-8") as fh:
            fh.write(line)
