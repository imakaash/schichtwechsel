"""Thin client for the Bundesagentur fuer Arbeit job search.

The API has no official documentation. Endpoints and the public client id
follow the community spec at https://jobsuche.api.bund.dev.

Search moved to v6 in 2026 and v4 search now answers 403. Details are
still served under v4.
"""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
CLIENT_ID = "jobboerse-jobsuche"
RETRY_STATUS = {429, 500, 502, 503, 504}

log = logging.getLogger(__name__)


class BAError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class BAClient:
    def __init__(
        self,
        *,
        pause: float = 0.5,
        timeout: float = 30.0,
        max_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.pause = pause
        self.max_retries = max_retries
        self._http = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            transport=transport,
            headers={
                "X-API-Key": CLIENT_ID,
                "User-Agent": "schichtwechsel/0.1 (non-commercial labour market research)",
            },
        )

    def __enter__(self) -> BAClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._http.get(path, params=params)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if resp.status_code == 200:
                    if self.pause:
                        time.sleep(self.pause)
                    return resp.json()
                if resp.status_code not in RETRY_STATUS:
                    raise BAError(
                        f"GET {path} -> {resp.status_code}: {resp.text[:200]}", resp.status_code
                    )
                last_error = BAError(f"GET {path} -> {resp.status_code}", resp.status_code)

            wait = 2**attempt
            log.warning("request failed (%s), retry %d in %ss", last_error, attempt + 1, wait)
            time.sleep(wait)

        raise BAError(f"giving up on {path}") from last_error

    def search(self, *, page: int = 1, size: int = 100, **params: Any) -> dict[str, Any]:
        query = {k: v for k, v in params.items() if v is not None}
        query.update(page=page, size=size)
        return self._get("/pc/v6/jobs", params=query)

    def iter_postings(
        self, *, max_pages: int = 60, size: int = 100, **params: Any
    ) -> Iterator[dict[str, Any]]:
        for page in range(1, max_pages + 1):
            data = self.search(page=page, size=size, **params)
            items = data.get("ergebnisliste") or data.get("stellenangebote") or []
            yield from items

            total = int(data.get("maxErgebnisse") or 0)
            if not items or page * size >= total:
                return
        log.warning("hit max_pages=%d for %s, results are truncated", max_pages, params)

    def job_details(self, refnr: str) -> dict[str, Any]:
        code = base64.b64encode(refnr.encode()).decode()
        return self._get(f"/pc/v4/jobdetails/{code}")
