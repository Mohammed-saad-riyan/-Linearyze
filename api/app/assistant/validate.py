"""Checks applied in code to every sentence of an Output B answer (SRS 1.8.2.9, 1.8.2.12).

1. Each quote must exist in the passage it cites. The quote we display is the slice of
   the original passage text, never the model's string, so a quote that differs only in
   diacritics or spacing is still shown exactly as the document has it.
2. Every number, date and proper name in the sentence must also appear in the sentence's
   own quotes. The model may rephrase; it may not introduce a figure.
"""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.text.arabic import find_original_span, normalize

_MONTHS = {
    **{
        m: i
        for i, m in enumerate(
            [
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            ],
            start=1,
        )
    },
    **{
        m[:3]: i
        for i, m in enumerate(
            [
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            ],
            start=1,
        )
        if m != "may"
    },
    **{
        normalize(m): i
        for i, m in enumerate(
            [
                "يناير",
                "فبراير",
                "مارس",
                "أبريل",
                "مايو",
                "يونيو",
                "يوليو",
                "أغسطس",
                "سبتمبر",
                "أكتوبر",
                "نوفمبر",
                "ديسمبر",
            ],
            start=1,
        )
    },
}
_MONTH_ALT = "|".join(sorted(map(re.escape, _MONTHS), key=len, reverse=True))
_DATE_PATTERNS = [
    (re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\s*,?\s+(\d{{4}})"), ("d", "m", "y")),
    (re.compile(rf"\b({_MONTH_ALT})\s+(\d{{1,2}}),?\s+(\d{{4}})"), ("m", "d", "y")),
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), ("y", "m", "d")),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), ("d", "m", "y")),
]
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# Capitalised words that start a clause or are generic enough not to be names.
_NOT_NAMES = {
    "The",
    "This",
    "That",
    "These",
    "Those",
    "A",
    "An",
    "It",
    "Its",
    "In",
    "On",
    "Under",
    "According",
    "Both",
    "Each",
    "Per",
    "For",
    "No",
    "Yes",
    "If",
    "Then",
    "However",
    "Also",
    "There",
    "Their",
    "They",
    "We",
    "Our",
    "Payment",
    "Invoices",
}
_NAME = re.compile(r"\b[A-Z][a-zA-Z]+(?:[- ][A-Z][a-zA-Z]+)*")
_CLAUSE_START = re.compile(r"(^|[.!?:;]\s+)$")


def find_dates(text: str) -> tuple[set[dt.date], list[tuple[int, int]]]:
    """Dates mentioned in `text` and the character spans they occupy (in normalized text)."""
    norm = normalize(text)
    dates: set[dt.date] = set()
    spans: list[tuple[int, int]] = []
    for pattern, order in _DATE_PATTERNS:
        for match in pattern.finditer(norm):
            parts = dict(zip(order, match.groups(), strict=True))
            month = parts["m"]
            month_no = int(month) if month.isdigit() else _MONTHS[month]
            try:
                dates.add(dt.date(int(parts["y"]), month_no, int(parts["d"])))
            except ValueError:
                continue
            spans.append(match.span())
    return dates, spans


def find_numbers(text: str, skip_spans: list[tuple[int, int]] | None = None) -> set[Decimal]:
    """Numbers in `text`, with thousands separators removed. 12,000 and ١٢٬٠٠٠ are equal."""
    norm = normalize(text)
    found = set()
    for match in _NUMBER.finditer(norm):
        if skip_spans and any(s <= match.start() < e for s, e in skip_spans):
            continue
        raw = match.group()
        # A comma followed by exactly three digits is a thousands separator.
        cleaned = re.sub(r",(?=\d{3}(?:\D|$))", "", raw).replace(",", ".")
        try:
            found.add(Decimal(cleaned).normalize())
        except InvalidOperation:
            continue
    return found


def find_names(text: str, known_names: list[str]) -> set[str]:
    """Capitalised spans (English) plus any known organisation name, all normalized."""
    names = {
        normalize(n)
        for n in known_names
        if normalize(n) and f" {normalize(n)} " in f" {normalize(text)} "
    }
    for match in _NAME.finditer(text):
        words = re.split(r"[- ]", match.group())
        # One capitalised word at the start of a clause is just capitalisation.
        if len(words) == 1 and _CLAUSE_START.search(text[: match.start()]):
            continue
        while words and words[0] in _NOT_NAMES:
            words.pop(0)
        if words:
            names.add(normalize(" ".join(words)))
    return names


@dataclass
class VerifiedQuote:
    passage_id: int
    start: int
    end: int
    text: str  # the slice of the original passage


@dataclass
class SentenceCheck:
    quotes: list[VerifiedQuote] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.quotes)


def check_sentence(
    sentence: str,
    quotes: list[tuple[int, str]],
    passages: dict[int, str],
    known_names: list[str],
    cited_titles: dict[int, str] | None = None,
) -> SentenceCheck:
    """`cited_titles` maps passage ids to their document titles. A sentence may name the
    document it cites ("The Booth Services Order states ..."): the title is the citation
    label shown on the card, not a fact taken from the text."""
    result = SentenceCheck()
    for passage_id, quote in quotes:
        source = passages.get(passage_id)
        span = find_original_span(source, quote) if source is not None and quote.strip() else None
        if span is None:
            result.errors.append(f"quote not found in passage {passage_id}: {quote!r}")
            continue
        result.quotes.append(VerifiedQuote(passage_id, span[0], span[1], source[span[0] : span[1]]))  # type: ignore[index]
    if not result.quotes:
        result.errors.append("sentence has no verified quote")
        return result

    quoted = " ".join(q.text for q in result.quotes)
    sentence_dates, date_spans = find_dates(sentence)
    quoted_dates, _ = find_dates(quoted)
    for missing in sorted(sentence_dates - quoted_dates):
        result.errors.append(f"date {missing.isoformat()} is not in the quotes")
    numbers = find_numbers(sentence, date_spans)
    quoted_numbers = (
        find_numbers(quoted)
        | {Decimal(d.day) for d in quoted_dates}
        | {Decimal(d.year) for d in quoted_dates}
    )
    for missing_n in sorted(numbers - quoted_numbers):
        result.errors.append(f"number {missing_n} is not in the quotes")
    quoted_norm = f" {normalize(quoted)} "
    titles = " | ".join(
        normalize(cited_titles[q.passage_id])
        for q in result.quotes
        if cited_titles and q.passage_id in cited_titles
    )
    for name in sorted(find_names(sentence, known_names)):
        if name in titles:
            continue
        if f" {name} " not in quoted_norm and name not in quoted_norm:
            result.errors.append(f"name '{name}' is not in the quotes")
    return result
