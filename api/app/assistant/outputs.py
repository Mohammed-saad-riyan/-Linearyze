"""Deterministic choice of output A to E (SRS 1.6.1 to 1.6.11, 1.7.1).

A  one document card            B  answer with verbatim quotes
C  clarifying question          D  list of document cards
E  a defined message only (M1, M2, payment refusal)

This is a pure function of the grade and the retrieval counts; the model has no say.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from app.assistant.grade_types import Grade
from app.assistant.messages import MessageId

OutputKind = Literal["A", "B", "C", "D", "E"]


@dataclass(frozen=True)
class Selection:
    output: OutputKind
    message_id: MessageId | None = None


def select_output(
    grade: Grade,
    *,
    plan_impossible: bool,
    document_count: int,
    passage_count: int,
) -> Selection:
    if grade == "OT":
        # 1.6.11: payment requests are OT like any other out-of-scope query, and get M2.
        # The 0.10.7 payment message belongs to the Advisor (2.1.6).
        return Selection("E", "M2")
    if grade == "AM":
        return Selection("C")
    if plan_impossible:
        return Selection("E", "M1")
    if grade == "DR":
        if document_count == 0:
            return Selection("E", "M1")
        return Selection("A") if document_count == 1 else Selection("D")
    return Selection("B") if passage_count > 0 else Selection("E", "M1")


def order_documents(
    hits: list[tuple[str, float, dt.date | None]],
) -> list[str]:
    """Output D order (SRS 1.8.4.3, 1.8.4.5): relevance, then newest, then id.

    Same input, same order, every time: the id is the final tie-break.
    """
    return [
        doc_id
        for doc_id, _, _ in sorted(
            hits, key=lambda h: (-h[1], -(h[2] or dt.date.min).toordinal(), h[0])
        )
    ]
