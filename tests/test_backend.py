import time

import httpx
import pytest

from schichtwechsel.agent.limits import LimitReached, SpendLimiter
from schichtwechsel.ui import backend


@pytest.fixture
def paths(tmp_path, monkeypatch):
    warehouse = tmp_path / "data" / "warehouse.duckdb"
    marker = warehouse.with_suffix(".downloaded")
    monkeypatch.setattr(backend, "WAREHOUSE", warehouse)
    monkeypatch.setattr(backend, "MARKER", marker)
    calls = []

    def fake_download(url, target):
        calls.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"copy {len(calls)}")
        marker.write_text(str(time.time()))

    monkeypatch.setattr(backend, "_download", fake_download)
    return warehouse, marker, calls


def test_downloads_when_missing(paths):
    warehouse, _, calls = paths
    backend.ensure_warehouse("https://example.org/w.duckdb")
    assert calls == ["https://example.org/w.duckdb"] and warehouse.read_text() == "copy 1"


def test_local_copy_is_never_replaced(paths):
    warehouse, _, calls = paths
    warehouse.parent.mkdir(parents=True)
    warehouse.write_text("my local data")
    backend.ensure_warehouse("u", now=time.time() + 10 * 86400)
    assert calls == [] and warehouse.read_text() == "my local data"


def test_downloaded_copy_refreshes_when_stale(paths):
    warehouse, marker, calls = paths
    backend.ensure_warehouse("u")
    backend.ensure_warehouse("u", now=time.time() + 60)  # fresh: no second download
    assert len(calls) == 1
    backend.ensure_warehouse("u", now=time.time() + backend.REFRESH_SECONDS + 60)
    assert len(calls) == 2 and warehouse.read_text() == "copy 2"


def test_failed_refresh_keeps_serving(paths, monkeypatch):
    warehouse, marker, _ = paths
    backend.ensure_warehouse("u")

    def broken(url, target):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(backend, "_download", broken)
    assert backend.ensure_warehouse("u", now=time.time() + 10 * 86400) == warehouse
    assert warehouse.read_text() == "copy 1"


def test_spend_limiter():
    limiter = SpendLimiter(daily_budget_usd=0.5, max_questions=2)
    limiter.admit("a")
    limiter.record(0.3)
    limiter.admit("a")
    with pytest.raises(LimitReached, match="question limit"):
        limiter.admit("a")
    limiter.record(0.3)
    with pytest.raises(LimitReached, match="daily budget"):
        limiter.admit("b")
