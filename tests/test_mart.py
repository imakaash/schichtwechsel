from datetime import date, datetime

import pytest

from schichtwechsel.storage import Warehouse

MON, TUE, NEXT_MON = date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 26)


def posting(refnr, region="BERLIN", occupation="Verkäufer/in", offer_type=1, **extra):
    return {
        "refnr": refnr,
        "offer_type": offer_type,
        "occupation": occupation,
        "region": region,
        "title": extra.pop("title", "Verkäufer (m/w/d)"),
        "published_on": MON,
        **extra,
    }


def snap(wh, day, competitor, rows):
    wh.replace_snapshot(day, competitor, [r | {"competitor": competitor} for r in rows])


@pytest.fixture
def wh(tmp_path):
    with Warehouse(tmp_path / "wh.duckdb") as warehouse:
        yield warehouse


def test_role_and_track_fallbacks(wh):
    cases = {
        "Filialleiter/in, Verkaufsstellenleiter/in": "store_management",
        "Helfer/in - Verkauf": "store_sales",
        "Fachverkäufer/in - Nahrungsmittelhandwerk (Bäckerei/Konditorei)": "store_sales",
        "Kommissionierer/in": "logistics",
        "Berufskraftfahrer/in": "driving",
        "Helfer/in - Reinigung": "other",
        "Data Scientist": "head_office",
        None: "other",
    }
    for occupation, role in cases.items():
        assert wh.scalar("SELECT role_from_occupation(?)", [occupation]) == role

    assert wh.scalar("SELECT track_from_posting(4, 'Duales Studium BWL (B.A.)')") == "dual_study"
    assert wh.scalar("SELECT track_from_posting(4, 'Ausbildung Verkäufer')") == "apprenticeship"
    assert wh.scalar("SELECT track_from_posting(1, 'Aushilfe Kasse')") == "side_job"


def test_hiring_pressure_index_is_relative_to_national_rate(wh):
    # Berlin: 3 store_sales postings, Bremen: 1; Bremen has about a fifth of Berlin's people
    snap(wh, MON, "dm", [posting("b1"), posting("b2"), posting("h1", region="BREMEN")])
    snap(wh, MON, "lidl", [posting("b3"), posting("x1", region=None)])

    rows = wh.query(
        "SELECT region, open_postings, drugstore_postings, pressure_index FROM mart.hiring_pressure"
    ).set_index("region")
    pop = wh.query("SELECT region, population FROM ref_population").set_index("region")[
        "population"
    ]
    rate = 4 / pop.sum()

    assert rows.loc["BERLIN", "open_postings"] == 3
    assert rows.loc["BERLIN", "drugstore_postings"] == 2
    assert rows.loc["BERLIN", "pressure_index"] == pytest.approx(
        100 * 3 / pop["BERLIN"] / rate, abs=0.1
    )
    assert rows.loc["BREMEN", "pressure_index"] == pytest.approx(
        100 * 1 / pop["BREMEN"] / rate, abs=0.1
    )
    assert wh.scalar("SELECT without_location FROM mart.coverage WHERE competitor = 'lidl'") == 1


def test_weekly_average_divides_by_days_observed(wh):
    snap(wh, MON, "dm", [posting("a"), posting("b")])
    snap(wh, TUE, "dm", [posting("a")])
    snap(wh, TUE, "rossmann", [posting("r")])  # only seen on one of two days

    weekly = wh.query(
        "SELECT competitor, avg_open_postings FROM mart.open_postings_weekly ORDER BY competitor"
    )
    assert weekly.to_dict("records") == [
        {"competitor": "dm", "avg_open_postings": 1.5},
        {"competitor": "rossmann", "avg_open_postings": 0.5},
    ]


def test_flow_skips_backlog_and_counts_disappearances(wh):
    snap(wh, MON, "dm", [posting("old"), posting("gone")])
    snap(wh, TUE, "dm", [posting("old"), posting("new")])
    snap(wh, NEXT_MON, "dm", [posting("old"), posting("new")])

    flow = wh.query(
        "SELECT week::VARCHAR AS week, new_postings, closed_postings FROM mart.posting_flow"
    )
    assert flow.to_dict("records") == [
        {"week": "2026-10-19", "new_postings": 1, "closed_postings": 1}
    ]


def test_snapshot_health_flags_drops_and_missing_competitors(wh):
    snap(wh, MON, "dm", [posting(f"d{i}") for i in range(10)])
    snap(wh, MON, "aldi", [posting("a1")])
    snap(wh, TUE, "dm", [posting(f"d{i}") for i in range(6)])

    health = wh.query(
        "SELECT competitor, status FROM mart.snapshot_health WHERE snapshot_date = ?", [TUE]
    ).set_index("competitor")["status"]
    assert health["dm"] == "drop"
    assert health["aldi"] == "empty"
    assert health["kaufland"] == "empty"  # never seen counts too


def test_employer_scale_uses_store_counts(wh):
    snap(wh, MON, "dm", [posting("a"), posting("b", offer_type=4)])
    row = wh.query("SELECT * FROM mart.employer_scale").iloc[0]
    stores = wh.scalar("SELECT stores_de FROM ref_store_counts WHERE competitor = 'dm'")
    assert row["postings_per_100_stores"] == round(200 / stores, 1)
    assert row["apprenticeship_postings"] == 1


def test_feature_views_report_shares_with_their_n(wh):
    snap(wh, MON, "dm", [posting("p1"), posting("p2"), posting("p3")])
    for refnr, text_hash in (("p1", "t1"), ("p2", "t2")):
        wh.upsert(
            "posting_details",
            [{
                "refnr": refnr, "competitor": "dm", "fetched_at": datetime.now(),
                "status": "ok", "text_hash": text_hash, "school_level": None, "temp_agency": False,
            }],
        )  # fmt: skip
    wh.upsert(
        "posting_features",
        [
            {
                "text_hash": "t1", "extractor_version": "v", "extracted_at": datetime.now(),
                "role_family": "store_sales", "track": "regular", "pay_min": 15.0, "pay_max": 17.0,
                "pay_period": "hour", "tariff": "above_tariff",
                "benefits": ["staff_discount", "public_transport"],
            },
            {
                "text_hash": "t2", "extractor_version": "v", "extracted_at": datetime.now(),
                "role_family": "store_sales", "track": "regular", "tariff": "not_mentioned",
                "benefits": ["staff_discount"],
            },
        ],
    )  # fmt: skip

    pay = wh.query("SELECT * FROM mart.pay_transparency").iloc[0]
    assert pay["postings_with_text"] == 2
    assert pay["share_pay_stated"] == 0.5 and pay["share_tariff_reference"] == 0.5
    assert pay["median_hourly_pay"] == 16.0

    benefits = wh.query(
        "SELECT benefit, postings_mentioning, share FROM mart.benefits_matrix ORDER BY benefit"
    )
    assert benefits.to_dict("records") == [
        {"benefit": "public_transport", "postings_mentioning": 1, "share": 0.5},
        {"benefit": "staff_discount", "postings_mentioning": 2, "share": 1.0},
    ]
    assert wh.scalar("SELECT with_features FROM mart.coverage") == 2
