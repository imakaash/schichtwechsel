"""Batch extraction: submit pending texts, collect results, keep failures.

A text counts as done once it has a row in posting_features for the
current extractor version. Model-side failures (invalid output, failed
checks, refusals) are retried once, then stay in extraction_failures.
API-side failures (errored, expired, canceled requests) do not use up an
attempt.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from pydantic import ValidationError

from schichtwechsel.extract.prompt import SYSTEM, user_message
from schichtwechsel.extract.schema import PostingFeatures, grounding_problems
from schichtwechsel.storage import Warehouse

# bump when the model, the prompt or the schema changes
EXTRACTOR_VERSION = "2026-10-25"
MODEL = "claude-haiku-5-5"
MAX_ATTEMPTS = 2
MAX_CHARS = 40_000
SCHEMA = anthropic.transform_schema(PostingFeatures)

log = logging.getLogger(__name__)


@dataclass
class Outcome:
    features: PostingFeatures | None
    reason: str | None
    raw: str | None
    input_tokens: int = 0
    output_tokens: int = 0


def request_params(text: str) -> dict[str, Any]:
    return {
        "model": MODEL,
        "max_tokens": 4096,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": user_message(text)}],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
    }


def judge(message: Any, text: str) -> Outcome:
    """Turn one model response into features or a failure reason."""
    usage = getattr(message, "usage", None)
    tokens = {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
    }
    if message.stop_reason == "refusal":
        return Outcome(None, "refusal", None, **tokens)
    if message.stop_reason == "max_tokens":
        return Outcome(None, "truncated", None, **tokens)

    raw = next((b.text for b in message.content if b.type == "text"), None)
    if raw is None:
        return Outcome(None, "no text block", None, **tokens)
    try:
        features = PostingFeatures.model_validate_json(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "root"
        return Outcome(None, f"invalid: {where}: {first['msg']}", raw, **tokens)

    problems = grounding_problems(features, text)
    if problems:
        return Outcome(None, "ungrounded: " + "; ".join(problems), raw, **tokens)
    return Outcome(features, None, raw, **tokens)


def _feature_row(text_hash: str, outcome: Outcome) -> dict[str, Any]:
    return {
        "text_hash": text_hash,
        "extractor_version": EXTRACTOR_VERSION,
        "extracted_at": datetime.now(),
        **outcome.features.model_dump(mode="json"),
        "input_tokens": outcome.input_tokens,
        "output_tokens": outcome.output_tokens,
    }


def _failure_row(
    text_hash: str, reason: str, raw: str | None, batch_id: str | None
) -> dict[str, Any]:
    return {
        "text_hash": text_hash,
        "extractor_version": EXTRACTOR_VERSION,
        "batch_id": batch_id,
        "failed_at": datetime.now(),
        "reason": reason,
        "raw_output": raw,
    }


def pending_texts(wh: Warehouse, limit: int) -> list[tuple[str, str]]:
    """Texts still to extract, the most reused first: they cover the most postings.

    Texts above MAX_CHARS are left out; `sw extract status` counts them.
    """
    rows = wh.query(
        """
        SELECT t.text_hash, t.body
        FROM posting_texts t
        JOIN posting_details d USING (text_hash)
        WHERE t.chars <= ?
          AND NOT EXISTS (
                SELECT 1 FROM posting_features f
                WHERE f.text_hash = t.text_hash AND f.extractor_version = ?)
          AND NOT EXISTS (
                SELECT 1 FROM extraction_batch_items i
                JOIN extraction_batches b USING (batch_id)
                WHERE i.text_hash = t.text_hash AND b.collected_at IS NULL)
          AND (SELECT count(*) FROM extraction_failures x
               WHERE x.text_hash = t.text_hash AND x.extractor_version = ?
                 AND x.reason NOT LIKE 'api:%') < ?
        GROUP BY t.text_hash, t.body
        ORDER BY count(*) DESC, t.text_hash
        LIMIT ?
        """,
        [MAX_CHARS, EXTRACTOR_VERSION, EXTRACTOR_VERSION, MAX_ATTEMPTS, limit],
    )
    return list(rows.itertuples(index=False, name=None))


def submit(client: anthropic.Anthropic, wh: Warehouse, limit: int) -> str | None:
    texts = pending_texts(wh, limit)
    if not texts:
        return None

    batch = client.messages.batches.create(
        requests=[
            Request(custom_id=h, params=MessageCreateParamsNonStreaming(**request_params(t)))
            for h, t in texts
        ]
    )
    wh.upsert(
        "extraction_batches",
        [
            {
                "batch_id": batch.id,
                "extractor_version": EXTRACTOR_VERSION,
                "submitted_at": datetime.now(),
                "requests": len(texts),
                "collected_at": None,
            }
        ],
    )
    wh.upsert("extraction_batch_items", [{"batch_id": batch.id, "text_hash": h} for h, _ in texts])
    log.info("submitted batch %s with %d texts", batch.id, len(texts))
    return batch.id


def collect(client: anthropic.Anthropic, wh: Warehouse) -> dict[str, Counter[str]]:
    """Read every finished batch that has not been collected yet."""
    open_ids = wh.query("SELECT batch_id FROM extraction_batches WHERE collected_at IS NULL")
    summary: dict[str, Counter[str]] = {}

    for batch_id in open_ids["batch_id"]:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            log.info("batch %s still %s", batch_id, batch.processing_status)
            continue

        bodies = dict(
            wh.query(
                """
                SELECT t.text_hash, t.body FROM extraction_batch_items i
                JOIN posting_texts t USING (text_hash) WHERE i.batch_id = ?
                """,
                [batch_id],
            ).itertuples(index=False, name=None)
        )
        features, failures, counts = [], [], Counter()
        for item in client.messages.batches.results(batch_id):
            text_hash = item.custom_id
            if item.result.type != "succeeded":
                failures.append(_failure_row(text_hash, f"api: {item.result.type}", None, batch_id))
                counts[f"api: {item.result.type}"] += 1
                continue
            outcome = judge(item.result.message, bodies[text_hash])
            if outcome.features is not None:
                features.append(_feature_row(text_hash, outcome))
                counts["ok"] += 1
            else:
                failures.append(_failure_row(text_hash, outcome.reason, outcome.raw, batch_id))
                counts[outcome.reason.split(":")[0]] += 1

        wh.upsert("posting_features", features)
        wh.append("extraction_failures", failures)
        wh.con.execute(
            "UPDATE extraction_batches SET collected_at = ? WHERE batch_id = ?",
            [datetime.now(), batch_id],
        )
        summary[batch_id] = counts
    return summary


def extract_one(client: anthropic.Anthropic, text: str) -> Outcome:
    """Same request as the batch, sent directly. For trying out prompt changes."""
    message = client.messages.create(**request_params(text))
    return judge(message, text)
