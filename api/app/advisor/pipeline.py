"""The Operational Advisor request, end to end (SRS 2.1 to 2.9).

    grade -> formula (user's, or AI-selected and labelled) -> parse -> bind every term
          -> R (result) | Q (what is missing or must be chosen) | E (M12, payment, M2)

Output R shows the result, the formula line exactly as given, the same line with values
substituted, and every input with where it came from.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from app.advisor.bind import Binding, Figure, bind_terms
from app.advisor.evaluate import (
    CalculationError,
    FormulaNotApplicable,
    MixedCurrencies,
    Quantity,
    Unit,
    evaluate,
    format_number,
    round_result,
)
from app.advisor.formula import Formula, FormulaError, Var, display, parse_formula, variables
from app.advisor.grade import FinalAdvisorGrade, grade
from app.assistant.grade_offline import requested_version
from app.assistant.messages import Lang, MessageId, message
from app.assistant.pipeline import Citation, DocumentCard, SourceRef, _cards, render_message
from app.assistant.plan import Plan, resolve_event
from app.db.session import Conn
from app.text.arabic import detect_language

AdvisorOutput = Literal["R", "Q", "E"]

_UNIT_WORDS: dict[str, dict[Lang, tuple[str, str]]] = {
    # base: lang -> (singular, plural)
    "SAR": {"en": ("SAR", "SAR"), "ar": ("ريال", "ريال")},
    "booth": {"en": ("booth", "booths"), "ar": ("جناح", "جناح")},
    "visitor": {"en": ("visitor", "visitors"), "ar": ("زائر", "زائر")},
    "ticket": {"en": ("ticket", "tickets"), "ar": ("تذكرة", "تذكرة")},
    "day": {"en": ("day", "days"), "ar": ("يوم", "يوم")},
}

TEXT: dict[str, dict[Lang, str]] = {
    "rounded_up": {
        "en": "Rounded up from {exact} to {value}: a part of a {unit} cannot be sold.",
        "ar": "تم التقريب إلى الأعلى من {exact} إلى {value}، إذ لا يمكن بيع جزء من {unit}.",
    },
    "before_tax": {
        "en": "Amounts are before tax: no tax rate was given.",
        "ar": "المبالغ قبل الضريبة، إذ لم تُحدَّد نسبة ضريبة.",
    },
    "ai_selected": {
        "en": "No formula was given, so the assistant selected this definition. Check it before relying on the result.",
        "ar": "لم تُحدَّد معادلة، لذلك اختار المساعد هذا التعريف. يرجى مراجعته قبل الاعتماد على النتيجة.",
    },
    "override": {
        "en": "Your value for {term} was used instead of the document value {doc_value}.",
        "ar": "استُخدمت القيمة التي حددتها لـ{term} بدلاً من قيمة المستند {doc_value}.",
    },
    "missing": {
        "en": "To calculate this I need values for: {terms}. Give them in your message, or tell me which document states them.",
        "ar": "لإجراء هذا الحساب أحتاج إلى قيم: {terms}. يرجى ذكرها في رسالتك أو تحديد المستند الذي يتضمنها.",
    },
    "need_formula": {
        "en": "Which formula should I use? Write it with an equals sign, for example: profit = confirmed revenue - total cost.",
        "ar": "ما المعادلة التي تريد استخدامها؟ اكتبها بعلامة يساوي، مثل: الربح = الإيرادات المؤكدة - إجمالي التكاليف.",
    },
    "malformed": {
        "en": "I could not read the formula near “{part}”: {reason}. Please correct that part.",
        "ar": "تعذّرت قراءة المعادلة عند “{part}”. يرجى تصحيح هذا الجزء.",
    },
    "currency": {
        "en": "The values are in different currencies ({currencies}). What exchange rate should I use?",
        "ar": "القيم بعملات مختلفة ({currencies}). ما سعر الصرف الذي يجب استخدامه؟",
    },
    "choose_value": {
        "en": "Documents give different values for {term}. Which one should I use?",
        "ar": "تذكر المستندات قيماً مختلفة لـ{term}. أيّها أستخدم؟",
    },
    "clarify": {
        "en": "Do you want a figure from the documents, or a calculation? If a calculation, please give the formula.",
        "ar": "هل تريد رقماً من المستندات أم عملية حسابية؟ إن كانت عملية حسابية فيرجى ذكر المعادلة.",
    },
}


def unit_text(unit: Unit | None, lang: Lang, value: Decimal | None = None) -> str:
    if not unit:
        return ""
    plural = value is None or value != 1
    up = [b for b, e in unit if e > 0]
    down = [b for b, e in unit if e < 0]
    words = [_UNIT_WORDS.get(b, {"en": (b, b), "ar": (b, b)})[lang][1 if plural else 0] for b in up]
    text = " ".join(words)
    for b in down:
        word = _UNIT_WORDS.get(b, {"en": (b, b), "ar": (b, b)})[lang][0]
        text += f" per {word}" if lang == "en" else f" لكل {word}"
    return text.strip()


class Input(BaseModel):
    term: str
    value: str
    unit: str
    source_type: str
    document_id: str | None = None
    document_title: str | None = None
    citation: Citation | None = None
    overridden_value: str | None = None
    overridden_document_title: str | None = None
    overridden_citation: Citation | None = None


class Result(BaseModel):
    value: str
    unit: str
    exact: str
    rounded_up: bool


class ChoiceOption(BaseModel):
    value: str
    document_title: str
    citation: Citation


class AdvisorResponse(BaseModel):
    output: AdvisorOutput
    lang: Lang
    notice: str | None = None  # M7 when documents disagree on an input
    result: Result | None = None
    formula: str | None = None
    formula_source: str | None = None
    substituted: str | None = None
    inputs: list[Input] = []
    notes: list[str] = []
    estimate: bool = False
    question: str | None = None
    missing: list[str] = []
    choices: list[ChoiceOption] = []
    documents: list[DocumentCard] = []
    disclaimer: str | None = None
    debug: dict[str, Any] | None = None


@dataclass
class AdvisorOutcome:
    body: bytes
    output: AdvisorOutput
    message_id: MessageId | None
    grade: str | None


def _citation(conn: Conn, figure: Figure) -> Citation | None:
    if figure.chunk_id is None or figure.document_id is None:
        return None
    row = conn.execute(
        "SELECT page, heading, sheet, cell_range FROM chunks WHERE id = %s", (figure.chunk_id,)
    ).fetchone()
    assert row is not None, "a bound figure always points at an existing chunk"
    return Citation(
        document_id=figure.document_id,
        chunk_id=figure.chunk_id,
        quote=figure.quote or "",
        start=figure.quote_start or 0,
        end=figure.quote_end or 0,
        source=SourceRef(**row),
    )


def _titles(conn: Conn, ids: set[str]) -> dict[str, str]:
    return {
        r["id"]: r["title"]
        for r in conn.execute(
            "SELECT id, title FROM documents WHERE id = ANY(%s)", (list(ids),)
        ).fetchall()
    }


def _q(lang: Lang, question: str, graded: FinalAdvisorGrade, **extra: Any) -> AdvisorOutcome:
    response = AdvisorResponse(output="Q", lang=lang, question=question, **extra)
    return AdvisorOutcome(
        response.model_dump_json(exclude_none=True).encode(), "Q", None, graded.grade
    )


def _e(message_id: MessageId, lang: Lang, graded: FinalAdvisorGrade) -> AdvisorOutcome:
    return AdvisorOutcome(render_message(message_id, lang), "E", message_id, graded.grade)


def run(conn: Conn, query: str, history: list[str], debug: bool = False) -> AdvisorOutcome:
    lang: Lang = "ar" if detect_language(query) == "ar" else "en"
    graded = grade(query, history)
    if graded.grade == "OT":
        return _e("PAYMENT" if graded.payment_request else "M2", lang, graded)
    if graded.grade == "AM":
        return _q(lang, TEXT["clarify"][lang], graded)

    formula: Formula | None = None
    if graded.grade == "CALC":
        if not graded.formula_text:
            return _q(lang, TEXT["need_formula"][lang], graded)
        try:
            formula = parse_formula(graded.formula_text)
        except FormulaError as exc:
            return _q(lang, TEXT["malformed"][lang].format(part=exc.part, reason=exc), graded)
        term_list = variables(formula.expression)
    else:
        label = graded.result.lookup_term or query
        term_list = [Var(label, label)]

    event_id = resolve_event(conn, f"{graded.result.context or ''} {query}")
    # A figure "from version 1 of the price list" binds against that version only (1.2.13).
    plan = Plan(event_id=event_id, version=requested_version(query))
    context = graded.result.context or ""
    remainder = (
        query.replace(graded.formula_text or "", " ") if graded.formula_source == "user" else query
    )
    bindings = bind_terms(conn, plan, term_list, remainder, history, context)

    conflicted = [b for b in bindings if b.conflict]
    if conflicted:
        b = conflicted[0]
        assert b.conflict is not None
        titles = _titles(conn, {f.document_id for f in b.conflict if f.document_id})
        choices = []
        for figure in b.conflict:
            citation = _citation(conn, figure)
            if citation and figure.document_id:
                choices.append(
                    ChoiceOption(
                        value=f"{format_number(figure.value)} {unit_text(figure.unit, lang, figure.value)}".strip(),
                        document_title=titles[figure.document_id],
                        citation=citation,
                    )
                )
        return _q(
            lang,
            TEXT["choose_value"][lang].format(term=b.term.label),
            graded,
            notice=message("M7", lang),
            choices=choices,
        )

    missing = [b.term.label for b in bindings if b.figure is None]
    if missing:
        if graded.grade == "LKP":
            # 2.9.3: the same M9 whether the figure is absent or only in documents the
            # user cannot read; RLS makes those two cases identical before we get here.
            return _e("M9", lang, graded)
        separator = "، " if lang == "ar" else ", "
        return _q(
            lang,
            TEXT["missing"][lang].format(terms=separator.join(missing)),
            graded,
            missing=missing,
        )

    figures = {b.term.name: b.figure for b in bindings if b.figure is not None}
    if formula is not None:
        try:
            raw = evaluate(
                formula.expression, {n: Quantity(f.value, f.unit) for n, f in figures.items()}
            )
            rounded = round_result(raw)
        except MixedCurrencies as exc:
            return _q(
                lang,
                TEXT["currency"][lang].format(currencies=", ".join(sorted(exc.currencies))),
                graded,
            )
        except FormulaNotApplicable:
            return _e("M11", lang, graded)
        except CalculationError:
            return _e("M12", lang, graded)
        result_unit = raw.unit
    else:
        only = next(iter(figures.values()))
        rounded = round_result(Quantity(only.value, only.unit))
        result_unit = only.unit

    return _render_r(conn, lang, graded, formula, bindings, rounded, result_unit, debug)


def _render_r(
    conn: Conn,
    lang: Lang,
    graded: FinalAdvisorGrade,
    formula: Formula | None,
    bindings: list[Binding],
    rounded: Any,
    result_unit: Unit | None,
    debug: bool,
) -> AdvisorOutcome:
    doc_ids = {
        f.document_id for b in bindings for f in (b.figure, b.overridden) if f and f.document_id
    }
    titles = _titles(conn, doc_ids)
    inputs, notes = [], []
    substituted_values = {}
    for b in bindings:
        figure = b.figure
        assert figure is not None
        substituted_values[b.term.name] = format_number(figure.value)
        item = Input(
            term=b.term.label,
            value=format_number(figure.value),
            unit=unit_text(figure.unit, lang, figure.value),
            source_type=figure.source_type,
            document_id=figure.document_id,
            document_title=titles.get(figure.document_id or ""),
            citation=_citation(conn, figure),
        )
        if b.overridden is not None:
            item.overridden_value = format_number(b.overridden.value)
            item.overridden_document_title = titles.get(b.overridden.document_id or "")
            item.overridden_citation = _citation(conn, b.overridden)
            notes.append(
                TEXT["override"][lang].format(term=b.term.label, doc_value=item.overridden_value)
            )
        inputs.append(item)

    unit = unit_text(result_unit, lang, rounded.value)
    if rounded.note == "rounded_up":
        notes.insert(
            0,
            TEXT["rounded_up"][lang].format(
                exact=format_number(rounded.exact),
                value=format_number(rounded.value),
                unit=unit_text(result_unit, lang, Decimal(1)),
            ),
        )
    money = any(base == "SAR" for base, _ in result_unit or ())
    taxed = any(
        "tax" in b.term.name or "vat" in b.term.name or "ضريب" in b.term.name for b in bindings
    )
    if money and not taxed:
        notes.append(TEXT["before_tax"][lang])
    if graded.formula_source == "ai_selected":
        notes.insert(0, TEXT["ai_selected"][lang])

    estimate = graded.result.is_scenario or any(
        b.figure and b.figure.source_type != "document" for b in bindings
    )
    response = AdvisorResponse(
        output="R",
        lang=lang,
        result=Result(
            value=format_number(rounded.value),
            unit=unit,
            exact=format(rounded.exact, "f"),
            rounded_up=rounded.note == "rounded_up",
        ),
        formula=formula.text if formula else None,
        formula_source=graded.formula_source,
        substituted=display(formula.expression, substituted_values) if formula else None,
        inputs=inputs,
        notes=notes,
        estimate=estimate,
        documents=_cards(conn, sorted(doc_ids), lang),
        disclaimer=message("M8", lang),
        debug={
            "grade": graded.grade,
            "grade_reason": graded.reason,
            "scores": graded.result.scores.model_dump(),
            "terms": [b.term.name for b in bindings],
        }
        if debug
        else None,
    )
    return AdvisorOutcome(
        response.model_dump_json(exclude_none=True).encode(), "R", None, graded.grade
    )
