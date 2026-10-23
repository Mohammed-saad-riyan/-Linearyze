"""Bind each formula term to a figure (SRS 2.8).

Sources, in order of precedence:
1. a value the user typed in this query ("assuming a booth price of 11,000"),
2. a value from an earlier message in the conversation,
3. a quote from a document the user can read.

A user value overrides a document value, and both are shown (2.8.8). For a document
value, the model (or the offline matcher) only points at a passage and copies a quote and
the figure as written; code checks the quote is really in the passage, checks the figure
is really in the quote, and parses the number itself. The model never supplies a number
that is used in arithmetic.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import numpy as np
from pydantic import BaseModel

from app import llm
from app.advisor.evaluate import Unit, unit_of
from app.advisor.formula import Var
from app.assistant.answer import split_sentences
from app.assistant.plan import Plan
from app.assistant.retrieve import PassageHit, search_passages
from app.config import settings
from app.db.session import Conn
from app.embeddings import embed_query
from app.text.arabic import find_original_span, normalize
from app.text.terms import coverage, terms

_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_YEAR = re.compile(r"^(19|20)\d\d$")
_CURRENCY = re.compile(r"\b(sar|riyals?|ريال|ر\.س)\b|\(sar\)", re.IGNORECASE)
_PER = re.compile(r"\bper (booth|visitor|ticket|day)\b|لكل (جناح|زائر|تذكره|يوم)", re.IGNORECASE)
_PER_AR = {"جناح": "booth", "زائر": "visitor", "تذكره": "ticket", "يوم": "day"}


@dataclass
class Figure:
    value: Decimal
    value_text: str
    unit: Unit
    source_type: str  # "document" | "query" | "conversation"
    document_id: str | None = None
    chunk_id: int | None = None
    quote: str | None = None
    quote_start: int | None = None
    quote_end: int | None = None


@dataclass
class Binding:
    term: Var
    figure: Figure | None
    overridden: Figure | None = None  # the document value a user value replaced
    conflict: list[Figure] | None = None  # documents disagree; the user must choose


def parse_number(text: str) -> Decimal | None:
    match = _NUMBER.search(normalize(text))
    if match is None:
        return None
    try:
        return Decimal(match.group().replace(",", ""))
    except InvalidOperation:
        return None


def unit_from_text(text: str, term_label: str) -> Unit:
    norm = normalize(text)
    currency = 1 if _CURRENCY.search(norm) else 0
    per = _PER.search(norm)
    per_unit = None
    if per:
        per_unit = per.group(1) or _PER_AR.get(per.group(2) or "")
    # A "price" or "fee" without an explicit "per" in the quote is per item of the term:
    # "standard booth price" -> SAR per booth.
    if (
        per_unit is None
        and currency
        and re.search(r"\b(price|fee|rate)\b|سعر|رسوم", normalize(term_label))
    ):
        named = re.search(
            r"\b(booth|visitor|ticket|day)s?\b|(جناح|زائر|تذكره)", normalize(term_label)
        )
        if named:
            per_unit = named.group(1) or _PER_AR.get(named.group(2) or "")
    exponents: dict[str, int] = {}
    if currency:
        exponents["SAR"] = 1
    if per_unit:
        exponents[per_unit] = -1
    return unit_of(**exponents)


def usable_number(text: str) -> str | None:
    """The figure in a line, as written: the one next to a currency if there is one,
    otherwise the last number that is not a year."""
    norm = normalize(text)
    near_currency = re.search(r"(?:sar|ريال)\s*(\d[\d,.]*)|(\d[\d,.]*)\s*(?:sar|ريال)", norm)
    if near_currency:
        return (near_currency.group(1) or near_currency.group(2)).rstrip(".,")
    candidates = [m.group() for m in _NUMBER.finditer(norm) if not _YEAR.match(m.group())]
    return candidates[-1] if candidates else None


# --- values the user typed ---------------------------------------------------------------

# A typed amount with no currency for a money-like term ("the catering cost is 95,000")
# is taken to be in riyals, the company's reporting currency.
_MONEY_TERM = re.compile(
    r"\b(cost|costs|revenue|price|fee|amount|budget|income|expense)\b"
    r"|تكلف|تكاليف|ايراد|سعر|رسوم|مبلغ|ميزانيه|مصروف"
)


def _user_value(term: Var, texts: list[str], source_type: str) -> Figure | None:
    label = re.escape(normalize(term.label))
    patterns = [
        rf"{label}\s*(?:is|=|of|at|:|هو|هي|يساوي)?\s*(?:sar|ريال)?\s*(\d[\d,.]*)",
        rf"(\d[\d,.]*)\s*(?:sar|ريال)?\s*(?:for|as|ك)\s*(?:the\s+)?{label}",
    ]
    for text in texts:
        norm = normalize(text)
        for pattern in patterns:
            match = re.search(pattern, norm)
            if match:
                value_text = match.group(1).rstrip(".,")
                value = parse_number(value_text)
                if value is not None:
                    unit_text = norm
                    if not _CURRENCY.search(norm) and _MONEY_TERM.search(normalize(term.label)):
                        unit_text += " sar"
                    return Figure(
                        value, value_text, unit_from_text(unit_text, term.label), source_type
                    )
    return None


# --- values in documents -----------------------------------------------------------------


class PointedQuote(BaseModel):
    passage: int | None  # None: no passage states this figure
    quote: str = ""
    value_text: str = ""


def _point_live(term: Var, context: str, passages: list[PassageHit]) -> PointedQuote:
    listing = "\n\n".join(f"[{n}] {p.text}" for n, p in enumerate(passages, start=1))
    return llm.structured(
        "bind", f"Term: {term.label}\nContext: {context}\n\nPassages:\n{listing}", PointedQuote
    )


def _point_offline(term: Var, passages: list[PassageHit]) -> PointedQuote:
    wanted = terms(term.label)
    best: tuple[float, float, int, str] | None = None
    for n, passage in enumerate(passages, start=1):
        for heading, line in split_sentences(passage.text):
            if usable_number(line) is None:
                continue
            score = coverage(wanted, set(terms(f"{passage.heading or ''} {heading} {line}")))
            key = (score, passage.score, -n, line)
            if score > 0 and (best is None or key[:3] > best[:3]):
                best = key
    if best is None:
        return PointedQuote(passage=None)
    line = best[3]
    return PointedQuote(passage=-best[2], quote=line, value_text=usable_number(line) or "")


def _verify(pointed: PointedQuote, passages: list[PassageHit], term: Var) -> Figure | None:
    if pointed.passage is None or not 1 <= pointed.passage <= len(passages):
        return None
    passage = passages[pointed.passage - 1]
    span = find_original_span(passage.text, pointed.quote)
    if span is None:
        return None
    quote = passage.text[span[0] : span[1]]
    if not pointed.value_text or find_original_span(quote, pointed.value_text) is None:
        return None
    value = parse_number(pointed.value_text)
    if value is None:
        return None
    # A spreadsheet's column header row ("Cost item | Amount (SAR)") carries the unit.
    header = next(
        (
            line
            for line in passage.text.splitlines()
            if " | " in line and not any(ch.isdigit() for ch in line)
        ),
        "",
    )
    return Figure(
        value,
        pointed.value_text,
        unit_from_text(f"{header} {quote}", term.label),
        "document",
        passage.document_id,
        passage.chunk_id,
        quote,
        span[0],
        span[1],
    )


def _rival_figures(
    chosen: Figure, term: Var, passages: list[PassageHit], series: dict[str, str]
) -> list[Figure]:
    """Other documents that state this exact term with a different value (SRS 2.8, M7).

    Only lines naming every word of the term count, and versions of the chosen document
    do not: the latest version is the only one searched unless the user asks otherwise.
    """
    wanted = terms(term.label)
    rivals: dict[str, Figure] = {}
    for n, passage in enumerate(passages, start=1):
        if series[passage.document_id] == series[chosen.document_id or ""]:
            continue
        for heading, line in split_sentences(passage.text):
            value_text = usable_number(line)
            if value_text is None or coverage(wanted, set(terms(f"{heading} {line}"))) < 1:
                continue
            figure = _verify(
                PointedQuote(passage=n, quote=line, value_text=value_text), passages, term
            )
            if figure and figure.value != chosen.value:
                rivals.setdefault(passage.document_id, figure)
    return list(rivals.values())


def _document_value(
    conn: Conn, plan: Plan, term: Var, context: str
) -> tuple[Figure | None, list[Figure]]:
    query = f"{term.label} {context}".strip()
    vector: np.ndarray = embed_query(query)
    # Live, the model points at the figure among the fused candidates and code verifies it,
    # so a rerank call per term buys little and costs rate limit. The offline matcher has no
    # judgement of its own and relies on the (free) offline reranker to filter.
    live = settings.use_live_cohere()
    passages = search_passages(conn, plan, query, vector, rerank_passages=not live)[:8]
    if not passages:
        return None, []
    pointed = (
        _point_live(term, context, passages)
        if settings.use_live_llm()
        else _point_offline(term, passages)
    )
    chosen = _verify(pointed, passages, term)
    if chosen is None:
        return None, []
    series = {
        r["id"]: r["series"]
        for r in conn.execute(
            "SELECT id, series FROM documents WHERE id = ANY(%s)",
            (list({p.document_id for p in passages}),),
        ).fetchall()
    }
    return chosen, _rival_figures(chosen, term, passages, series)


def bind_terms(
    conn: Conn,
    plan: Plan,
    term_list: list[Var],
    query_without_formula: str,
    history: list[str],
    context: str,
) -> list[Binding]:
    bindings = []
    for term in term_list:
        user = _user_value(term, [query_without_formula], "query") or _user_value(
            term, list(reversed(history)), "conversation"
        )
        document, rivals = _document_value(conn, plan, term, context)
        if user is not None and document is not None and not user.unit:
            # "assuming a booth price of 11,000": same kind of figure as the document's.
            user.unit = document.unit
        if user is not None:
            bindings.append(Binding(term, user, overridden=document))
        elif rivals and document is not None:
            bindings.append(Binding(term, None, conflict=[document, *rivals]))
        else:
            bindings.append(Binding(term, document))
    return bindings
