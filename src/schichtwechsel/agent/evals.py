"""Golden-question evals for the analyst agent.

Runs every question in evals/questions.yaml in a fresh session, checks the
answer, and writes a JSON report to data/evals/. Expected values come from
SQL run at eval time, so the suite follows the data.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from schichtwechsel.agent.checks import language_of, mentions
from schichtwechsel.agent.executor import ReadOnlyMart
from schichtwechsel.agent.loop import Session
from schichtwechsel.config import DATA_DIR, ROOT

QUESTIONS = ROOT / "evals" / "questions.yaml"
REPORTS = DATA_DIR / "evals"


@dataclass
class Outcome:
    id: str
    lang: str
    question: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    answer: str = ""
    declined: str | None = None
    queries: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0


def load(path: Path = QUESTIONS) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text("utf-8"))


def expected_values(mart: ReadOnlyMart, sql: str) -> list[float]:
    result = mart.run("expected", sql, "eval")
    if result.error:
        raise ValueError(f"expect_sql failed: {result.error}")
    row = result.rows[0] if result.rows else []
    return [float(v) for v in row if isinstance(v, int | float) and not isinstance(v, bool)]


def judge(case: dict[str, Any], answer, expected: list[float]) -> list[str]:
    failures = []
    accepted = case.get("expect_decline")
    if accepted:
        if answer.declined not in accepted:
            failures.append(f"expected decline {accepted}, got {answer.declined}")
    elif answer.declined:
        failures.append(f"declined ({answer.declined}) but should answer")
    if answer.refused:
        failures.append("refused by the model")
    if not answer.grounded:
        failures.append(f"not grounded: {answer.checks}")
    found = language_of(answer.text)
    if found and found != case["lang"]:
        failures.append(f"answered in {found}, expected {case['lang']}")
    for value in expected:
        if not mentions(answer.text, value):
            failures.append(f"missing expected value {value:g}")
    texts = case.get("expect_text_any")
    if texts and not any(t.lower() in answer.text.lower() for t in texts):
        failures.append(f"none of {texts} in the answer")
    return failures


def run_case(client, case: dict[str, Any]) -> Outcome:
    mart = ReadOnlyMart()
    try:
        expected = expected_values(mart, case["expect_sql"]) if case.get("expect_sql") else []
        answer = Session(client, mart).ask(case["question"], case["lang"])
    finally:
        mart.close()
    failures = judge(case, answer, expected)
    return Outcome(
        id=case["id"],
        lang=case["lang"],
        question=case["question"],
        passed=not failures,
        failures=failures,
        answer=answer.text,
        declined=answer.declined,
        queries=len(answer.queries),
        cost_usd=answer.cost_usd,
        seconds=answer.seconds,
    )


def run(client, cases: list[dict[str, Any]], workers: int = 4) -> tuple[list[Outcome], Path]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(lambda c: run_case(client, c), cases))
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(
        json.dumps(
            {
                "run_at": datetime.now().isoformat(timespec="seconds"),
                "passed": sum(o.passed for o in outcomes),
                "total": len(outcomes),
                "cost_usd": round(sum(o.cost_usd for o in outcomes), 4),
                "outcomes": [asdict(o) for o in outcomes],
            },
            ensure_ascii=False,
            indent=1,
        ),
        "utf-8",
    )
    return outcomes, path
