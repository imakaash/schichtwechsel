"""Full posting text from the BA details endpoint.

Search results carry no description, so each posting costs one extra
request. That is slow against a shared public API, so we fetch newest
first with a per-competitor cap and only for postings we have not seen.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from datetime import datetime

from schichtwechsel.ba_client import BAClient, BAError
from schichtwechsel.storage import Warehouse

log = logging.getLogger(__name__)


def compose(title: str | None, body: str | None) -> str | None:
    """The text we extract from. The title often carries hours ("3-25 Std./Wo.")."""
    body = (body or "").strip()
    if not body:
        return None
    return f"{(title or '').strip()}\n\n{body}"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def pending(wh: Warehouse, competitors: list[str], per_competitor: int) -> list[tuple[str, str]]:
    """Postings from the latest snapshot without details yet, newest first."""
    rows = wh.query(
        """
        SELECT s.competitor, s.refnr
        FROM postings_snapshot s
        LEFT JOIN posting_details d USING (refnr)
        WHERE s.snapshot_date = (SELECT max(snapshot_date) FROM postings_snapshot)
          AND d.refnr IS NULL
          AND list_contains(?, s.competitor)
        QUALIFY row_number() OVER (
            PARTITION BY s.competitor ORDER BY s.published_on DESC NULLS LAST, s.refnr
        ) <= ?
        """,
        [competitors, per_competitor],
    )
    return list(rows.itertuples(index=False, name=None))


def fetch_details(client: BAClient, wh: Warehouse, todo: list[tuple[str, str]]) -> Counter[str]:
    statuses: Counter[str] = Counter()
    details, texts = [], {}

    for i, (competitor, refnr) in enumerate(todo, 1):
        row = {
            "refnr": refnr,
            "competitor": competitor,
            "fetched_at": datetime.now(),
            "text_hash": None,
            "school_level": None,
            "temp_agency": None,
        }
        try:
            raw = client.job_details(refnr)
        except BAError as exc:
            if exc.status != 404:
                raise
            row["status"] = "gone"
        else:
            text = compose(raw.get("stellenangebotsTitel"), raw.get("stellenangebotsBeschreibung"))
            row["status"] = "ok" if text else "no_text"
            row["school_level"] = raw.get("geforderterBildungsabschluss")
            row["temp_agency"] = raw.get("istArbeitnehmerUeberlassung")
            if text:
                row["text_hash"] = text_hash(text)
                texts[row["text_hash"]] = {
                    "text_hash": row["text_hash"],
                    "body": text,
                    "chars": len(text),
                }
        details.append(row)
        statuses[row["status"]] += 1

        # write in chunks so an interrupted run keeps what it fetched
        if i % 100 == 0 or i == len(todo):
            wh.upsert("posting_texts", list(texts.values()))
            wh.upsert("posting_details", details)
            log.info("details: %d/%d (%s)", i, len(todo), dict(statuses))
            details, texts = [], {}

    return statuses
