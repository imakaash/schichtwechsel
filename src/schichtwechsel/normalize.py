"""Turn raw BA postings into flat rows for the warehouse.

Field names in the raw payload are German and occasionally missing, so
every lookup is defensive. Anything we do not map stays available in the
raw files.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


PART_TIME_FLAGS = (
    "arbeitszeitTeilzeitVormittag",
    "arbeitszeitTeilzeitNachmittag",
    "arbeitszeitTeilzeitAbend",
    "arbeitszeitTeilzeitFlexibel",
)


def _flag(raw: dict[str, Any], key: str) -> bool | None:
    value = raw.get(key)
    return value if isinstance(value, bool) else None


def _part_time(raw: dict[str, Any]) -> bool | None:
    flags = [raw[k] for k in PART_TIME_FLAGS if isinstance(raw.get(k), bool)]
    return any(flags) if flags else None


def _location(raw: dict[str, Any]) -> tuple[dict[str, Any], float | None, float | None, int]:
    """First listed location. v6 sends a list, v4 sent a single `arbeitsort`."""
    places = raw.get("stellenlokationen") or []
    if places:
        first = places[0]
        return (
            first.get("adresse") or {},
            _float(first.get("breite")),
            _float(first.get("laenge")),
            len(places),
        )
    place = raw.get("arbeitsort") or {}
    coords = place.get("koordinaten") or {}
    return place, _float(coords.get("lat")), _float(coords.get("lon")), 1 if place else 0


def employer_of(raw: dict[str, Any]) -> str | None:
    return raw.get("firma") or raw.get("arbeitgeber")


def posting_row(raw: dict[str, Any], *, competitor: str, offer_type: int) -> dict[str, Any]:
    place, lat, lon, n_places = _location(raw)
    start = raw.get("eintrittszeitraum") or {}
    published = raw.get("veroeffentlichungszeitraum") or {}
    return {
        "competitor": competitor,
        "offer_type": offer_type,
        "refnr": raw.get("referenznummer") or raw.get("refnr"),
        "title": raw.get("stellenangebotsTitel") or raw.get("titel"),
        "occupation": raw.get("hauptberuf") or raw.get("beruf"),
        "employer": employer_of(raw),
        "plz": place.get("plz"),
        "city": place.get("ort"),
        "region": place.get("region"),
        "country": place.get("land"),
        "lat": lat,
        "lon": lon,
        "location_count": n_places,
        "published_on": _date(published.get("von") or raw.get("aktuelleVeroeffentlichungsdatum")),
        "first_published_on": _date(raw.get("datumErsteVeroeffentlichung")),
        "start_on": _date(start.get("von") or raw.get("eintrittsdatum")),
        "modified_at": _timestamp(raw.get("aenderungsdatum") or raw.get("modifikationsTimestamp")),
        "full_time": _flag(raw, "arbeitszeitVollzeit"),
        "part_time": _part_time(raw),
        "shift_work": _flag(raw, "arbeitszeitSchichtNachtWochenende"),
        "minijob": _flag(raw, "istGeringfuegigeBeschaeftigung"),
        "career_changer_ok": _flag(raw, "quereinstiegGeeignet"),
        "pay_info": raw.get("verguetungsangabe"),
        "contract_term": raw.get("vertragsdauer"),
        "external_url": raw.get("externeURL") or raw.get("externeUrl"),
    }
