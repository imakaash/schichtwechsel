"""Hand labels for measuring extraction accuracy.

`export` writes a workbook with one block per posting: fields to fill on
the left, the posting text on the right. Labels are filled in blind, not
pre-filled with model output, so they stay independent of it. `score`
reads the workbook back and compares it with the current extraction.

Conventions in the sheet: an empty enum cell means "not stated" (or "not
mentioned"), an empty number means null, a benefit counts when marked x.
Only blocks marked done are scored.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from schichtwechsel.extract.runner import EXTRACTOR_VERSION
from schichtwechsel.extract.schema import (
    Benefit,
    Contract,
    EntryRequirement,
    GermanLevel,
    PayPeriod,
    RoleFamily,
    Tariff,
    Track,
)
from schichtwechsel.storage import Warehouse

ENUMS: dict[str, type[StrEnum]] = {
    "role_family": RoleFamily,
    "track": Track,
    "entry_requirement": EntryRequirement,
    "contract": Contract,
    "pay_period": PayPeriod,
    "tariff": Tariff,
    "german_level": GermanLevel,
}
NUMBERS = ["hours_min", "hours_max", "pay_min", "pay_max", "staff_discount_pct", "vacation_days"]
ORDER = [
    "role_family", "track", "entry_requirement", "hours_min", "hours_max", "contract",
    "pay_min", "pay_max", "pay_period", "tariff", "staff_discount_pct", "vacation_days",
    "german_level",
]  # fmt: skip
# what an empty cell stands for; fields without a default are skipped when empty
EMPTY_MEANS = {
    "entry_requirement": "not_stated",
    "contract": "not_stated",
    "tariff": "not_mentioned",
    "german_level": "not_mentioned",
}
HINTS = {
    "role_family": "Pflicht",
    "track": "Pflicht",
    "entry_requirement": "leer = nicht genannt",
    "hours_min": "Std./Woche, leer = nicht genannt",
    "hours_max": "Std./Woche",
    "contract": "leer = nicht genannt",
    "pay_min": "nur genannte Euro-Beträge, Grundlohn",
    "pay_max": "bei einem Betrag gleich pay_min",
    "pay_period": "leer wenn kein Betrag",
    "tariff": "leer = nicht erwähnt",
    "staff_discount_pct": "Prozent",
    "vacation_days": "Tage bei 5-Tage-Woche, 6 Wochen = 30",
    "german_level": "leer = nicht erwähnt",
}
DONE = "done"
HEADER = "#"

QUOTA = {"dm": 8, "rossmann": 8, "lidl": 8, "aldi": 8, "kaufland": 8, "budni": 8, "mueller": 2}

_HEAD_FILL = PatternFill("solid", fgColor="1F3A4D")
_INPUT_FILL = PatternFill("solid", fgColor="FFF6DD")


def sample(wh: Warehouse, quota: dict[str, int], seed: int = 7) -> list[dict[str, Any]]:
    rows = wh.query(
        """
        SELECT DISTINCT d.competitor, t.text_hash, t.body
        FROM posting_texts t JOIN posting_details d USING (text_hash)
        ORDER BY d.competitor, t.text_hash
        """
    ).to_dict("records")
    rng = random.Random(seed)
    picked = []
    for competitor, n in quota.items():
        pool = [r for r in rows if r["competitor"] == competitor]
        picked += rng.sample(pool, min(n, len(pool)))
    rng.shuffle(picked)
    return picked


def export(wh: Warehouse, path: Path, quota: dict[str, int] = QUOTA) -> int:
    postings = sample(wh, quota)
    wb = Workbook()
    ws = wb.active
    ws.title = "Labels"
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 34
    ws.column_dimensions["D"].width = 3
    ws.column_dimensions["E"].width = 110

    lists = {name: [m.value for m in enum] for name, enum in ENUMS.items()}
    lists["benefit"] = ["x"]
    lists[DONE] = ["ja"]
    validations = {}
    for name, values in lists.items():
        dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        validations[name] = dv

    row = 1
    for i, posting in enumerate(postings, 1):
        title, _, body = posting["body"].partition("\n\n")
        ws.cell(row, 1, HEADER)
        ws.cell(row, 2, f"{i} / {len(postings)}  {posting['competitor']}")
        ws.cell(row, 3, posting["text_hash"])
        ws.cell(row, 5, title)
        for col in range(1, 6):
            cell = ws.cell(row, col)
            cell.fill = _HEAD_FILL
            cell.font = Font(bold=True, color="FFFFFF")

        keys = [DONE, *ORDER, *(f"benefit:{b.value}" for b in Benefit)]
        paragraphs = [p.strip() for p in body.split("\n") if p.strip()]
        for offset in range(max(len(keys), len(paragraphs))):
            r = row + 1 + offset
            if offset < len(keys):
                key = keys[offset]
                ws.cell(r, 1, key)
                value = ws.cell(r, 2)
                value.fill = _INPUT_FILL
                kind = "benefit" if key.startswith("benefit:") else key
                if kind in validations:
                    validations[kind].add(value)
                hint = "ja, wenn fertig gelabelt" if key == DONE else HINTS.get(key, "x = genannt")
                ws.cell(r, 3, hint).font = Font(color="777777", size=9)
            if offset < len(paragraphs):
                text = ws.cell(r, 5, paragraphs[offset])
                text.alignment = Alignment(wrap_text=True, vertical="top")
        row += 2 + max(len(keys), len(paragraphs))

    ws.freeze_panes = "A2"
    _guide(wb.create_sheet("Anleitung"))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return len(postings)


def _guide(ws) -> None:
    lines = [
        "So wird gelabelt",
        "",
        "Pro Stellenanzeige ein Block: links die Felder, rechts der Anzeigentext.",
        "Nur eintragen, was in der Anzeige steht. Nichts aus Erfahrung ergänzen.",
        "Gelbe Zellen ausfüllen, Auswahl über das Dropdown.",
        "Leere Zelle: nicht genannt. Benefit: x, wenn ausdrücklich genannt.",
        "Am Ende 'done' auf 'ja' setzen. Nur fertige Blöcke werden ausgewertet.",
        "",
        "Codes",
        "role_family: store_sales (Verkauf, Kasse, Warenverräumung), store_management "
        "(Filialleitung, Stellvertretung), logistics, head_office, technical, driving, other",
        "track: apprenticeship (Ausbildung), dual_study, internship, side_job (Aushilfe, "
        "Studentenjob, Minijob), seasonal_temp (Weihnachtsaushilfe), regular",
        "entry_requirement: none (Quereinsteiger willkommen), vocational (Ausbildung erwartet), "
        "degree",
        "pay_min / pay_max: Grundlohn in Euro, keine Zulagen oder Zuschläge",
        "tariff: above_tariff (übertariflich), tariff (nach Tarif, Tarifregelungen)",
        "contract: fixed_term auch bei Hinweis auf die Dauer der Befristung",
        "german_level: basic, good, fluent (auch: beherrscht die deutsche Sprache)",
    ]
    ws.column_dimensions["A"].width = 120
    for i, line in enumerate(lines, 1):
        ws.cell(i, 1, line).font = Font(bold=i in (1, 9))


@dataclass
class Score:
    n: int = 0
    correct: int = 0
    true_positives: int = 0
    misses: list[tuple[str, Any, Any]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0


def read_labels(path: Path) -> dict[str, dict[str, Any]]:
    ws = load_workbook(path, read_only=True).active
    labels: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for key, value, extra, *_ in ws.iter_rows(min_col=1, max_col=3, values_only=True):
        if key == HEADER:
            current = labels.setdefault(str(extra), {"_competitor": str(value).split()[-1]})
        elif current is not None and isinstance(key, str):
            current[key] = value
    return {h: v for h, v in labels.items() if str(v.get(DONE) or "").strip().lower() == "ja"}


def _label_value(key: str, raw: Any) -> Any:
    empty = raw is None or str(raw).strip() == ""
    if key in NUMBERS:
        return None if empty else float(str(raw).replace(",", "."))
    return EMPTY_MEANS.get(key) if empty else str(raw).strip()


def _same(key: str, label: Any, model: Any) -> bool:
    if key in NUMBERS:
        if label is None or model is None:
            return label is None and model is None
        return abs(float(label) - float(model)) < 0.01
    return label == model


def score(wh: Warehouse, path: Path) -> tuple[dict[str, Score], dict[str, Score], int]:
    labels = read_labels(path)
    rows = wh.query(
        "SELECT * FROM posting_features WHERE extractor_version = ?", [EXTRACTOR_VERSION]
    )
    # DuckDB returns missing numbers as NaN; the comparison needs None
    rows = rows.astype(object).where(rows.notna(), None)
    model = {r["text_hash"]: r for r in rows.to_dict("records")}
    fields = {key: Score() for key in ORDER}
    benefits = {b.value: Score() for b in Benefit}

    for text_hash, label in labels.items():
        out = model.get(text_hash)
        who = f"{label['_competitor']} {text_hash[:8]}"
        for key in ORDER:
            if label.get(key) in (None, "") and key in ("role_family", "track"):
                continue
            want = _label_value(key, label.get(key))
            got = out[key] if out else "(no output)"
            fields[key].n += 1
            if out and _same(key, want, got):
                fields[key].correct += 1
            else:
                fields[key].misses.append((who, want, got))
        got_benefits = set(out["benefits"]) if out else set()
        for code, s in benefits.items():
            want = str(label.get(f"benefit:{code}") or "").strip().lower() == "x"
            s.n += 1
            s.true_positives += want and code in got_benefits
            if want == (code in got_benefits):
                s.correct += 1
            else:
                s.misses.append((who, want, code in got_benefits))
    return fields, benefits, len(labels)
