"""Conflict detection across documents (SRS 1.8.2.13 to 1.8.2.16).

Facts are read from the verified quotes only. The model (or the offline pattern) names the
fact and copies the value; code parses the value and does the comparison, so "30 days"
and "٣٠ يوماً" are equal and "SAR 12,000" and "12000 riyals" are equal. Versions of one
document are not a conflict: the older version is excluded upstream unless asked for.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from app import llm
from app.assistant.answer import AnswerSentence
from app.assistant.validate import VerifiedQuote, find_dates, find_numbers
from app.config import settings
from app.text.arabic import normalize


class Fact(BaseModel):
    quote_index: int
    fact_key: str
    value: str


class Facts(BaseModel):
    facts: list[Fact]


@dataclass
class ConflictValue:
    document_id: str
    value: str
    quote: VerifiedQuote


@dataclass
class Conflict:
    fact_key: str
    values: list[ConflictValue]


# Offline stand-in: a number with its unit, and the unit is the key.
_UNIT_PATTERNS = [
    (re.compile(r"(\d[\d,.]*)\s*(days?|يوما|يوم|ايام)"), "days"),
    (re.compile(r"(?:sar|ريال)\s*(\d[\d,.]*)|(\d[\d,.]*)\s*(?:sar|ريال)"), "sar"),
    (re.compile(r"(\d[\d,.]*)\s*(%|percent|بالمئه)"), "percent"),
]

# Words that would make the answer pick a side (SRS 1.8.2.15).
PREFERENCE_WORDS = re.compile(
    r"\b(correct|incorrect|prevails?|supersedes?|takes precedence|more reliable|"
    r"should be used|outdated|accurate|valid one)\b|الصحيح|الاصح|الادق|الاحدث|يعتمد|المعتمد",
)


def _facts_offline(quotes: list[str]) -> list[Fact]:
    facts = []
    for index, quote in enumerate(quotes):
        text = normalize(quote)
        for pattern, key in _UNIT_PATTERNS:
            for match in pattern.finditer(text):
                value = next(g for g in match.groups() if g)
                facts.append(Fact(quote_index=index, fact_key=key, value=value))
    return facts


def _comparable(value: str) -> tuple[object, ...]:
    dates, spans = find_dates(value)
    if dates:
        return tuple(sorted(dates))
    numbers: set[Decimal] = find_numbers(value, spans)
    return tuple(sorted(numbers)) if numbers else (normalize(value),)


def detect_conflicts(
    sentences: list[AnswerSentence],
    chunk_document: dict[int, str],
    document_series: dict[str, str],
) -> list[Conflict]:
    quotes = [q for s in sentences for q in s.quotes]
    if len({document_series[chunk_document[q.passage_id]] for q in quotes}) < 2:
        return []
    if settings.use_live_llm():
        listing = "\n".join(f"[{i}] {q.text}" for i, q in enumerate(quotes))
        facts = llm.structured("facts", f"Quotes:\n{listing}", Facts).facts
    else:
        facts = _facts_offline([q.text for q in quotes])

    by_key: dict[str, dict[str, ConflictValue]] = {}
    for fact in facts:
        if not 0 <= fact.quote_index < len(quotes):
            continue
        quote = quotes[fact.quote_index]
        document_id = chunk_document[quote.passage_id]
        by_key.setdefault(fact.fact_key, {}).setdefault(
            document_id, ConflictValue(document_id, fact.value, quote)
        )

    conflicts = []
    for key, per_document in sorted(by_key.items()):
        series = {document_series[d] for d in per_document}
        values = {_comparable(v.value) for v in per_document.values()}
        if len(series) > 1 and len(values) > 1:
            conflicts.append(
                Conflict(key, sorted(per_document.values(), key=lambda v: v.document_id))
            )
    return conflicts


def without_preference(sentences: list[AnswerSentence]) -> list[AnswerSentence]:
    return [s for s in sentences if not PREFERENCE_WORDS.search(normalize(s.text))]
