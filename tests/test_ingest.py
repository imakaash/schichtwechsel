import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from schichtwechsel.ba_client import BAClient, BAError
from schichtwechsel.config import Competitor, RadarConfig, SearchSettings
from schichtwechsel.ingest import take_snapshot
from schichtwechsel.normalize import posting_row
from schichtwechsel.storage import Warehouse

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "search_page.json").read_text("utf-8"))

DM = Competitor(key="dm", label="dm", segment="drugstore", query="dm", match="^dm[- ]drogerie")


def client_for(handler) -> BAClient:
    return BAClient(pause=0, max_retries=1, transport=httpx.MockTransport(handler))


def test_posting_row_maps_nested_fields():
    row = posting_row(FIXTURE["ergebnisliste"][0], competitor="dm", offer_type=1)
    assert row["refnr"] == "10000-1200000001-S"
    assert row["city"] == "Trier"
    assert row["lat"] == pytest.approx(49.7557)
    assert row["published_on"] == date(2026, 10, 20)
    assert row["start_on"] == date(2026, 11, 1)
    assert row["employer"] == "dm-drogerie markt GmbH + Co. KG"
    assert row["part_time"] is True and row["full_time"] is False
    assert row["location_count"] == 1


def test_posting_row_tolerates_missing_fields():
    row = posting_row(FIXTURE["ergebnisliste"][1], competitor="x", offer_type=1)
    assert row["plz"] is None and row["lat"] is None and row["start_on"] is None
    assert row["part_time"] is None and row["location_count"] == 0


def test_posting_row_reads_legacy_v4_shape():
    legacy = {
        "refnr": "10000-1-S",
        "titel": "Verkäufer",
        "arbeitgeber": "Lidl Vertriebs-GmbH",
        "arbeitsort": {"ort": "Trier", "koordinaten": {"lat": 49.7, "lon": 6.6}},
        "aktuelleVeroeffentlichungsdatum": "2026-10-20",
    }
    row = posting_row(legacy, competitor="lidl", offer_type=1)
    assert row["refnr"] == "10000-1-S" and row["employer"] == "Lidl Vertriebs-GmbH"
    assert row["lat"] == pytest.approx(49.7) and row["published_on"] == date(2026, 10, 20)


def test_employer_regex_drops_noise():
    assert DM.owns("dm-drogerie markt GmbH + Co. KG")
    assert not DM.owns("Steuerkanzlei Drogeriestraße")
    assert not DM.owns(None)


def test_pagination_stops_at_max_results():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/pc/v6/jobs")
        calls.append(request.url.params["page"])
        return httpx.Response(200, json=FIXTURE)

    items = list(client_for(handler).iter_postings(was="dm", size=1, max_pages=10))
    assert len(items) == 4  # 2 pages x 2 items, maxErgebnisse=2 with size=1
    assert calls == ["1", "2"]


def test_client_sends_api_key_and_raises_on_client_error():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "jobboerse-jobsuche"
        return httpx.Response(403, text="forbidden")

    with pytest.raises(BAError):
        client_for(handler).search(was="dm")


def test_snapshot_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("schichtwechsel.storage.RAW_DIR", tmp_path / "raw")
    import schichtwechsel.ingest as ingest

    monkeypatch.setattr(ingest, "write_raw", lambda items, **kw: None)
    cfg = RadarConfig(competitors=[DM], search=SearchSettings(offer_types=[1]))
    client = client_for(lambda r: httpx.Response(200, json=FIXTURE))
    day = date(2026, 10, 25)

    with Warehouse(tmp_path / "wh.duckdb") as wh:
        first = take_snapshot(cfg, [DM], client, wh, day=day)
        take_snapshot(cfg, [DM], client, wh, day=day)
        n = wh.query("SELECT count(*) AS n FROM postings_snapshot")["n"].iloc[0]
        life = wh.query("SELECT * FROM posting_lifecycle")

    assert first[0].returned == 2 and first[0].kept == 1
    assert n == 1
    assert bool(life["is_open"].iloc[0]) is True
    assert life["days_online"].iloc[0] == 5


def test_employer_list_replaces_free_text_search():
    comp = Competitor(
        key="m", label="M", segment="drugstore", employers=["A GmbH", "B GmbH"], match="^[ab] gmbh"
    )
    assert comp.searches() == [{"arbeitgeber": "A GmbH"}, {"arbeitgeber": "B GmbH"}]
    assert DM.searches() == [{"was": "dm"}]


def test_foreign_postings_are_out_of_scope():
    search = SearchSettings()
    assert search.in_scope("DEUTSCHLAND") and search.in_scope(None)
    assert not search.in_scope("OESTERREICH")
