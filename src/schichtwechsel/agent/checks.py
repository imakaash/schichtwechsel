"""Checks on the agent's final answer before it reaches the user.

Grounding: every figure in the answer must match a value from a query
result in this conversation, allowing for rounding to the precision
shown, German or English number formats, and shares written as percent.
Differences and ratios therefore have to be computed in SQL, which keeps
the arithmetic auditable. Round thousands may be rounded ("rund 1.200"
for 1,227). Exempt: figures the user wrote, years, and small whole
numbers (counting words like "the top 3"), and a few method constants
such as the 80 in P80.

Language: a stopword count, enough to catch an answer in the wrong
language, not a language model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

NUMBER = re.compile(r"(?<![\w.,])[-+]?\d+(?:[.,   ]\d{3})*(?:[.,]\d+)?(?![\w])")
DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
)
SMALL_WHOLE = 10
# Figures that belong to the method, not the data: P80, the index base of 100,
# "per 100,000 inhabitants", 12-month test periods. Exempt from grounding.
METHOD_CONSTANTS = {12.0, 80.0, 100.0, 100_000.0}


def _candidates(token: str) -> list[tuple[float, int]]:
    """Possible values of a written number, each with the decimals it shows."""
    t = re.sub(r"[   ]", "", token)
    out = []
    # German: dot groups thousands, comma marks decimals
    if re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+(,\d+)?|[-+]?\d+(,\d+)?", t):
        whole, _, frac = t.replace(".", "").partition(",")
        out.append((float(f"{whole}.{frac}" if frac else whole), len(frac)))
    # English: comma groups thousands, dot marks decimals
    if re.fullmatch(r"[-+]?\d{1,3}(,\d{3})+(\.\d+)?|[-+]?\d+(\.\d+)?", t):
        whole, _, frac = t.replace(",", "").partition(".")
        out.append((float(f"{whole}.{frac}" if frac else whole), len(frac)))
    return out


def numbers_in(text: str) -> list[str]:
    return NUMBER.findall(DATE.sub(" ", text))


def _values(results: Iterable[dict]) -> list[float]:
    values = []
    for result in results:
        for row in result.get("rows", []):
            for cell in row:
                if isinstance(cell, bool):
                    continue
                if isinstance(cell, int | float):
                    values.append(float(cell))
    return values


def _precision(value: float, decimals: int) -> int:
    """Round thousands ("rund 1.200") count as rounded at their last non-zero digit."""
    if decimals or abs(value) < 1000:
        return decimals
    digits = str(int(abs(value)))
    return -(len(digits) - len(digits.rstrip("0")))


def _matches(value: float, decimals: int, known: list[float]) -> bool:
    tolerance = 0.5 * 10 ** -_precision(value, decimals) + 1e-9
    for v in known:
        for scaled in (v, v * 100):
            if abs(value - scaled) <= tolerance or abs(value - abs(scaled)) <= tolerance:
                return True
    return False


def ungrounded(answer: str, results: Iterable[dict], question: str = "") -> list[str]:
    known = _values(results)
    asked = {c for tok in numbers_in(question) for c, _ in _candidates(tok)}
    missing = []
    for token in numbers_in(answer):
        options = _candidates(token)
        if not options:
            continue
        if any(v in asked for v, _ in options):
            continue
        if any(
            d == 0 and (abs(v) <= SMALL_WHOLE or 1990 <= v <= 2100 or v in METHOD_CONSTANTS)
            for v, d in options
        ):
            continue
        if not any(_matches(v, d, known) for v, d in options):
            missing.append(token)
    return missing


GERMAN = {
    "der", "die", "das", "und", "ist", "nicht", "mit", "auf", "für", "eine", "ein", "den",
    "dem", "im", "sind", "wir", "es", "von", "zu", "bei", "als", "auch", "wird", "werden",
    "hat", "haben", "noch", "nur", "oder", "wie", "aus", "nach", "über",
}  # fmt: skip
ENGLISH = {
    "the", "and", "is", "not", "with", "for", "a", "an", "of", "in", "are", "we", "it", "this",
    "that", "to", "on", "at", "as", "also", "will", "be", "has", "have", "only", "or", "how",
    "from", "after", "over", "than",
}  # fmt: skip


def language_of(text: str) -> str | None:
    words = re.findall(r"[a-zA-ZäöüßÄÖÜ]+", text.lower())
    de = sum(w in GERMAN for w in words)
    en = sum(w in ENGLISH for w in words)
    if de + en < 6:
        return None
    return "de" if de > en else "en"


def mentions(answer: str, value: float) -> bool:
    """Whether the answer states this value, at the precision it writes it."""
    for token in numbers_in(answer):
        if any(_matches(v, d, [value]) for v, d in _candidates(token)):
            return True
    return False
