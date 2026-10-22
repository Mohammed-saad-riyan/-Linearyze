"""Advisor grading (SRS 2.4): CALC, LKP (look up one figure), AM, OT.

The formula itself is never taken from the model when the user wrote one: code extracts
the "name = expression" clause from the query (formula.extract_formula_text). The model
proposes a formula only when the user gave none, and that formula is labelled as
AI-selected in the answer (SRS 2.6.3).
"""

import re
from typing import Literal

from pydantic import BaseModel

from app import llm
from app.advisor.formula import extract_formula_text
from app.assistant.grade import is_payment_request
from app.config import GRADE_GAP, settings
from app.text.arabic import normalize

AdvisorGrade = Literal["CALC", "LKP", "AM", "OT"]


class AdvisorScores(BaseModel):
    CALC: float = 0.0
    LKP: float = 0.0
    AM: float = 0.0
    OT: float = 0.0


class AdvisorGradeResult(BaseModel):
    scores: AdvisorScores
    lookup_term: str | None = None
    context: str | None = None
    is_payment_request: bool = False
    is_scenario: bool = False
    proposed_formula: str | None = None


class FinalAdvisorGrade(BaseModel):
    grade: AdvisorGrade
    reason: str
    result: AdvisorGradeResult
    formula_text: str | None
    formula_source: Literal["user", "ai_selected"] | None
    payment_request: bool = False


_SCENARIO = r"\b(assum\w*|what if|suppose|scenario|if we)\b|بافتراض|لو |اذا افترضنا|فرضا"
_QUESTION_WORDS = (
    r"^(what is|what's|what was|how much is|how much|how many|tell me|give me|find)\s+(the\s+|our\s+)?"
    r"|^(ما هو|ما هي|كم|اعطني)\s+"
)


def _offline(query: str) -> AdvisorGradeResult:
    q = normalize(query)
    has_formula = extract_formula_text(query) is not None
    term = re.sub(_QUESTION_WORDS, "", q).strip(" ?؟.")
    return AdvisorGradeResult(
        scores=AdvisorScores(CALC=1.0) if has_formula else AdvisorScores(LKP=1.0),
        lookup_term=None if has_formula else term,
        is_scenario=bool(re.search(_SCENARIO, q)),
    )


def grade(query: str, history: list[str]) -> FinalAdvisorGrade:
    if settings.use_live_llm():
        earlier = "\n".join(f"- {h}" for h in history[-5:]) or "(none)"
        result = llm.structured(
            "grade_advisor", f"Earlier messages:\n{earlier}\n\nQuery:\n{query}", AdvisorGradeResult
        )
    else:
        result = _offline(query)

    user_formula = extract_formula_text(query)
    if result.is_payment_request or is_payment_request(query):
        return FinalAdvisorGrade(
            grade="OT",
            reason="payment request (0.10.7)",
            result=result,
            formula_text=None,
            formula_source=None,
            payment_request=True,
        )
    if user_formula:
        return FinalAdvisorGrade(
            grade="CALC",
            reason="formula given",
            result=result,
            formula_text=user_formula,
            formula_source="user",
        )
    ranked = sorted(result.scores.model_dump().items(), key=lambda kv: kv[1], reverse=True)
    (top, top_score), (_, second) = ranked[0], ranked[1]
    if top_score - second < GRADE_GAP:
        return FinalAdvisorGrade(
            grade="AM",
            reason="top two scores close",
            result=result,
            formula_text=None,
            formula_source=None,
        )
    if top == "CALC":
        formula = result.proposed_formula
        return FinalAdvisorGrade(
            grade="CALC",
            reason="calculation, no formula given",
            result=result,
            formula_text=formula,
            formula_source="ai_selected" if formula else None,
        )
    return FinalAdvisorGrade(
        grade=top,
        reason="highest score",
        result=result,
        formula_text=None,
        formula_source=None,
    )
