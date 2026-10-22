"""Types shared by the live and offline graders."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Grade = Literal["DR", "IR", "AM", "OT"]
DateField = Literal["document_date", "received_date", "submitted_date"]


class Scores(BaseModel):
    DR: float = 0.0
    IR: float = 0.0
    AM: float = 0.0
    OT: float = 0.0


class Filters(BaseModel):
    doc_type: (
        Literal[
            "letter",
            "application",
            "contract",
            "price_list",
            "cost_sheet",
            "report",
            "memo",
            "policy",
            "proposal",
        ]
        | None
    ) = None
    sender: str | None = Field(None, description="organisation name as written in the query")
    recipient: str | None = None
    client: str | None = None
    direction: Literal["incoming", "outgoing"] | None = None
    date_field: DateField | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    event: str | None = None
    version: int | None = None


class DependentLookup(BaseModel):
    """'the day we submitted document X': find X first, then use one of its dates."""

    find_title: str
    use_field: DateField
    as_field: DateField


class GradeResult(BaseModel):
    scores: Scores
    requests: list[str]
    filters: Filters
    depends_on: DependentLookup | None = None
    topic: str | None = Field(None, description="what the query is about, without the filters")
    is_payment_request: bool = False
    query_en: str
    query_ar: str
