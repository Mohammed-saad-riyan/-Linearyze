"""Query grading for the Search Assistant (SRS 1.6).

DR  document retrieval: the user wants a document ("give me the letter ...")
IR  information retrieval: the user wants an answer from document content
AM  ambiguous: more than one request, or no clear winner between the above
OT  other: outside the assistant's job, including payment requests (0.10.7)

The model reads only the query, never document text, so a document cannot steer its own
grading (SRS 1.3.7). The model proposes scores and filters; the rules in `apply_rules`
make the final call and are unit-tested.
"""

import datetime as dt
import re

from pydantic import BaseModel

from app import llm
from app.assistant.grade_offline import grade_offline
from app.assistant.grade_types import Grade, GradeResult
from app.config import GRADE_GAP, settings
from app.text.arabic import normalize


class FinalGrade(BaseModel):
    grade: Grade
    reason: str
    result: GradeResult
    payment_request: bool = False


# SRS 1.6.11 / 0.10.7: requests to move money. Asking *about* payment terms is IR, so the
# patterns need an action verb aimed at a payment, not just the word "payment".
_PAYMENT_PATTERNS = [
    r"\b(pay|settle|transfer|wire|refund|remit)\b.*\b(invoice|amount|payment|bill|sar|riyal|fee|supplier|vendor|exhibitor)",
    r"\b(process|approve|make|send|release)\b.*\bpayments?\b",
    r"\b(pay|transfer)\s+(this|the|that|it|them|sar|\d)",
    r"(^|\s)(ادفع|سدد|حول|اصرف)\s|اعتمد الدفع|نفذ الدفع|دفع الفاتوره|سداد الفاتوره|حواله|تحويل مبلغ",
]
# "When do we have to pay the invoice?" asks about terms; it is not a request to pay.
_QUESTION_ABOUT_TERMS = (
    r"^(when|how (long|many|much)|what|which|is|are|does|do|متي|كم|ما|ماذا|هل)\b"
)


def is_payment_request(query: str) -> bool:
    q = normalize(query)
    if re.search(_QUESTION_ABOUT_TERMS, q):
        return False
    return any(re.search(p, q) for p in _PAYMENT_PATTERNS)


def apply_rules(result: GradeResult, query: str) -> FinalGrade:
    if result.is_payment_request or is_payment_request(query):
        return FinalGrade(
            grade="OT", reason="payment request (1.6.11)", result=result, payment_request=True
        )
    if len(result.requests) > 1:
        return FinalGrade(grade="AM", reason="more than one request (1.6.14)", result=result)
    ranked = sorted(result.scores.model_dump().items(), key=lambda kv: kv[1], reverse=True)
    (top, top_score), (_, second_score) = ranked[0], ranked[1]
    if top_score - second_score < GRADE_GAP:
        return FinalGrade(
            grade="AM", reason=f"top two scores within {GRADE_GAP} (1.6.12)", result=result
        )
    return FinalGrade(grade=top, reason="highest score", result=result)


def grade(query: str, today: dt.date) -> FinalGrade:
    if settings.use_live_llm():
        result = llm.structured(
            "grade_assistant", f"Today is {today.isoformat()}.\n\nQuery:\n{query}", GradeResult
        )
    else:
        result = grade_offline(query)
    return apply_rules(result, query)
