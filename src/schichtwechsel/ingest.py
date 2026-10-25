from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date

from schichtwechsel.ba_client import BAClient
from schichtwechsel.config import Competitor, RadarConfig
from schichtwechsel.normalize import employer_of, posting_row
from schichtwechsel.storage import Warehouse, write_raw

log = logging.getLogger(__name__)


@dataclass
class SnapshotResult:
    competitor: str
    returned: int
    kept: int
    stored: int

    @property
    def noise_share(self) -> float:
        return 1 - self.kept / self.returned if self.returned else 0.0


def take_snapshot(
    cfg: RadarConfig,
    competitors: list[Competitor],
    client: BAClient,
    warehouse: Warehouse,
    day: date | None = None,
) -> list[SnapshotResult]:
    day = day or date.today()
    results = []

    for comp in competitors:
        rows, returned, kept = [], 0, 0
        for offer_type in cfg.search.offer_types:
            matched = []
            for params in comp.searches():
                for item in client.iter_postings(
                    **params,
                    angebotsart=offer_type,
                    size=cfg.search.page_size,
                    max_pages=cfg.search.max_pages,
                ):
                    returned += 1
                    if not comp.owns(employer_of(item)):
                        continue
                    row = posting_row(item, competitor=comp.key, offer_type=offer_type)
                    if cfg.search.in_scope(row["country"]):
                        matched.append(item)
                        rows.append(row)

            kept += len(matched)
            write_raw(matched, day=day, name=f"{comp.key}_type{offer_type}")

        stored = warehouse.replace_snapshot(day, comp.key, rows)
        log.info("%s: %d returned, %d kept, %d stored", comp.key, returned, kept, stored)
        results.append(SnapshotResult(comp.key, returned, kept, stored))

    return results


def discover_employers(
    comp: Competitor, client: BAClient, pages: int = 3, size: int = 100
) -> list[tuple[str, int, bool]]:
    """Which employer names does a competitor's search term actually return?"""
    counts: Counter[str] = Counter()
    for params in comp.searches():
        for item in client.iter_postings(**params, angebotsart=1, size=size, max_pages=pages):
            counts[employer_of(item) or "(missing)"] += 1
    return [(name, n, comp.owns(name)) for name, n in counts.most_common()]
