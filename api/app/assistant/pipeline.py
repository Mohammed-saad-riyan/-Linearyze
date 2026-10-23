"""The Search Assistant request, end to end.

    grade -> plan -> retrieve under RLS -> select A..E -> [B] write, validate, conflicts
          -> render

M1 has a single exit: `render_message`. Whatever the cause (no such document, no access,
below threshold, not yet indexed), the response body is built from the message constant
alone, so all four are byte-identical. The HTTP layer adds the timing floor.
"""

import datetime as dt
import json
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.assistant.answer import write_answer
from app.assistant.conflict import detect_conflicts, without_preference
from app.assistant.grade import FinalGrade, grade
from app.assistant.messages import Lang, MessageId, message
from app.assistant.outputs import OutputKind, order_documents, select_output
from app.assistant.plan import Plan, build_plan
from app.assistant.retrieve import DocumentHit, PassageHit, find_documents, search_passages
from app.db.session import Conn
from app.embeddings import embed_query
from app.text.arabic import detect_language, normalize
from app.text.terms import or_tsquery

CLARIFY_QUESTION: dict[Lang, str] = {
    "en": "Your request could mean more than one thing. Which did you mean?",
    "ar": "يحتمل طلبك أكثر من معنى. أيّها تقصد؟",
}
CLARIFY_OTHER: dict[Lang, str] = {"en": "Something else", "ar": "شيء آخر"}
MAX_OPTIONS = 5  # SRS 1.8.3: up to five options plus "Other"


class SourceRef(BaseModel):
    page: int | None = None
    heading: str | None = None
    sheet: str | None = None
    cell_range: str | None = None


class Citation(BaseModel):
    document_id: str
    chunk_id: int
    quote: str
    start: int
    end: int
    source: SourceRef


class Sentence(BaseModel):
    text: str
    citations: list[Citation]


class DocumentCard(BaseModel):
    id: str
    title: str
    title_alt: str | None
    doc_type: str
    language: str
    reference: str | None
    date: dt.date | None
    date_kind: str | None  # received / submitted / dated
    sender: str | None
    recipient: str | None
    version: int
    is_latest: bool
    file_name: str
    mime_type: str
    view_chunk_id: int | None


class ConflictValueOut(BaseModel):
    document_id: str
    value: str
    citation: Citation


class ConflictOut(BaseModel):
    fact_key: str
    values: list[ConflictValueOut]


class AssistantResponse(BaseModel):
    output: OutputKind
    lang: Lang
    notice: str | None = None  # M7, shown first when documents disagree
    sentences: list[Sentence] = []
    conflicts: list[ConflictOut] = []
    documents: list[DocumentCard] = []
    question: str | None = None
    options: list[str] = []
    disclaimer: str | None = None  # M8 on every Output B
    debug: dict[str, Any] | None = None


@dataclass
class Outcome:
    body: bytes
    output: OutputKind
    message_id: MessageId | None
    grade: str | None = None
    excluded_count: int | None = None
    timings_ms: dict[str, int] = field(default_factory=dict)


def render_message(message_id: MessageId, lang: Lang, **placeholders: int) -> bytes:
    """Output E. Built from constants only; nothing about the request can reach it."""
    return json.dumps(
        {
            "output": "E",
            "lang": lang,
            "message_id": message_id,
            "message": message(message_id, lang, **placeholders),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def _cards(
    conn: Conn, ids: list[str], lang: Lang, view_chunks: dict[str, int] | None = None
) -> list[DocumentCard]:
    if not ids:
        return []
    name = "name_ar" if lang == "ar" else "name_en"
    rows = {
        r["id"]: r
        for r in conn.execute(
            f"""
        SELECT d.*, s.{name} AS sender_name, r.{name} AS recipient_name,
               (SELECT min(c.id) FROM chunks c WHERE c.document_id = d.id) AS first_chunk
        FROM documents d
        LEFT JOIN organizations s ON s.id = d.sender_org_id
        LEFT JOIN organizations r ON r.id = d.recipient_org_id
        WHERE d.id = ANY(%s)
        """,
            (ids,),
        ).fetchall()
    }
    cards = []
    for doc_id in ids:
        r = rows[doc_id]
        if r["received_date"]:
            date, kind = r["received_date"], "received"
        elif r["submitted_date"]:
            date, kind = r["submitted_date"], "submitted"
        else:
            date, kind = r["document_date"], "dated"
        cards.append(
            DocumentCard(
                id=r["id"],
                title=r["title"],
                title_alt=r["title_alt"],
                doc_type=r["doc_type"],
                language=r["language"],
                reference=r["reference_no"] or r["contract_no"],
                date=date,
                date_kind=kind,
                sender=r["sender_name"],
                recipient=r["recipient_name"],
                version=r["version"],
                is_latest=r["is_latest"],
                file_name=r["file_name"],
                mime_type=r["mime_type"],
                view_chunk_id=(view_chunks or {}).get(doc_id, r["first_chunk"]),
            )
        )
    return cards


def _citation(
    chunk_id: int, start: int, end: int, quote: str, chunk_rows: dict[int, dict[str, Any]]
) -> Citation:
    row = chunk_rows[chunk_id]
    return Citation(
        document_id=row["document_id"],
        chunk_id=chunk_id,
        quote=quote,
        start=start,
        end=end,
        source=SourceRef(
            page=row["page"],
            heading=row["heading"],
            sheet=row["sheet"],
            cell_range=row["cell_range"],
        ),
    )


def _debug(
    graded: FinalGrade,
    plan: Plan,
    passages: list[PassageHit],
    documents: list[DocumentHit],
    timings: dict[str, int],
    extra: dict[str, Any],
) -> dict[str, Any]:
    return {
        "grade": graded.grade,
        "grade_reason": graded.reason,
        "scores": graded.result.scores.model_dump(),
        "filters": graded.result.filters.model_dump(mode="json", exclude_none=True),
        "depends_on": graded.result.depends_on.model_dump() if graded.result.depends_on else None,
        "plan_notes": plan.notes,
        "documents": [
            {"id": d.document_id, "score": round(d.score, 3), "via": d.via} for d in documents
        ],
        "passages": [
            {
                "chunk_id": p.chunk_id,
                "document_id": p.document_id,
                "rerank_score": round(p.score, 3),
            }
            for p in passages[:10]
        ],
        "timings_ms": timings,
        **extra,
    }


def run(conn: Conn, query: str, today: dt.date, debug: bool = False) -> Outcome:
    lang: Lang = "ar" if detect_language(query) == "ar" else "en"
    timings: dict[str, int] = {}
    t0 = time.perf_counter()

    def lap(name: str) -> None:
        timings[name] = int((time.perf_counter() - t0) * 1000) - sum(timings.values())

    graded = grade(query, today)
    lap("grade")
    tsquery = or_tsquery(query)
    excluded_row = (
        conn.execute("SELECT excluded_match_count(%s) AS n", (tsquery,)).fetchone()
        if tsquery
        else None
    )
    excluded = excluded_row["n"] if excluded_row else 0

    def message_outcome(message_id: MessageId) -> Outcome:
        return Outcome(
            render_message(message_id, lang), "E", message_id, graded.grade, excluded, timings
        )

    if graded.grade == "OT":
        selection = select_output(
            "OT",
            plan_impossible=False,
            document_count=0,
            passage_count=0,
        )
        assert selection.message_id is not None
        return message_outcome(selection.message_id)

    if graded.grade == "AM":
        requests = graded.result.requests
        options = (
            requests[:MAX_OPTIONS]
            if len(requests) > 1
            else [
                ("Find the document: " if lang == "en" else "البحث عن المستند: ") + query,
                ("Answer from the documents: " if lang == "en" else "الإجابة من محتوى المستندات: ")
                + query,
            ]
        )
        response = AssistantResponse(
            output="C",
            lang=lang,
            question=CLARIFY_QUESTION[lang],
            options=[*options, CLARIFY_OTHER[lang]],
        )
        return Outcome(
            response.model_dump_json(exclude_none=True).encode(),
            "C",
            None,
            graded.grade,
            excluded,
            timings,
        )

    plan = build_plan(conn, graded.result)
    topic = plan.topic or query
    vector = embed_query(topic)
    passages: list[PassageHit] = []
    documents: list[DocumentHit] = []
    if not plan.impossible:
        if graded.grade == "DR":
            documents = find_documents(conn, plan, topic, vector)
        else:
            passages = search_passages(conn, plan, topic, vector)
    lap("retrieve")

    selection = select_output(
        graded.grade,
        plan_impossible=plan.impossible,
        document_count=len(documents),
        passage_count=len(passages),
    )
    if selection.output == "E":
        assert selection.message_id is not None
        return message_outcome(selection.message_id)

    extra: dict[str, Any] = {}
    if selection.output == "D" and all(d.via == "title" for d in documents):
        same_title = _same_title_options(conn, [d.document_id for d in documents], lang)
        if same_title:
            # 1.6.13: the name resolves to several documents, so ask which one.
            response = AssistantResponse(
                output="C",
                lang=lang,
                question=CLARIFY_QUESTION[lang],
                options=[*same_title[:MAX_OPTIONS], CLARIFY_OTHER[lang]],
            )
            return Outcome(
                response.model_dump_json(exclude_none=True).encode(),
                "C",
                None,
                graded.grade,
                excluded,
                timings,
            )

    if selection.output in ("A", "D"):
        dates = {
            r["id"]: r["document_date"]
            for r in conn.execute(
                "SELECT id, coalesce(received_date, submitted_date, document_date) AS document_date"
                " FROM documents WHERE id = ANY(%s)",
                ([d.document_id for d in documents],),
            ).fetchall()
        }
        ordered = order_documents(
            [(d.document_id, d.score, dates[d.document_id]) for d in documents]
        )
        response = AssistantResponse(
            output=selection.output, lang=lang, documents=_cards(conn, ordered, lang)
        )
    else:
        answered, extra = _answer(conn, query, lang, passages)
        lap("answer")
        if answered is None:
            return message_outcome("M1")
        response = answered

    if debug:
        response.debug = _debug(graded, plan, passages, documents, timings, extra)
    return Outcome(
        response.model_dump_json(exclude_none=True).encode(),
        response.output,
        None,
        graded.grade,
        excluded,
        timings,
    )


def _same_title_options(conn: Conn, ids: list[str], lang: Lang) -> list[str]:
    """If every document shares one title, an option per document naming what tells them
    apart: the other party, else the date. Empty if the titles differ."""
    name = "name_ar" if lang == "ar" else "name_en"
    rows = conn.execute(
        f"""
        SELECT d.id, d.title, d.document_date,
               coalesce(c.{name}, r.{name}) AS party
        FROM documents d
        LEFT JOIN organizations c ON c.id = d.client_org_id
        LEFT JOIN organizations r ON r.id = d.recipient_org_id AND r.id <> 'LNZ'
        WHERE d.id = ANY(%s) ORDER BY d.document_date, d.id
        """,
        (ids,),
    ).fetchall()
    if len({normalize(r["title"]) for r in rows}) != 1:
        return []
    joiner = " مع " if lang == "ar" else " with "
    return [
        f"{r['title']}{joiner}{r['party']}"
        if r["party"]
        else f"{r['title']} ({r['document_date']})"
        for r in rows
    ]


def _answer(
    conn: Conn, query: str, lang: Lang, passages: list[PassageHit]
) -> tuple[AssistantResponse | None, dict[str, Any]]:
    doc_ids = list(dict.fromkeys(p.document_id for p in passages))
    doc_rows = {
        r["id"]: r
        for r in conn.execute(
            "SELECT id, title, series FROM documents WHERE id = ANY(%s)", (doc_ids,)
        ).fetchall()
    }
    known_names = [
        r["alias_normalized"]
        for r in conn.execute(
            "SELECT alias_normalized FROM org_aliases WHERE length(alias_normalized) > 4"
        ).fetchall()
    ]
    result = write_answer(
        query, lang, passages, {d: r["title"] for d, r in doc_rows.items()}, known_names
    )
    chunk_rows = {
        r["id"]: r
        for r in conn.execute(
            "SELECT id, document_id, page, heading, sheet, cell_range FROM chunks WHERE id = ANY(%s)",
            ([p.chunk_id for p in passages],),
        ).fetchall()
    }
    chunk_document = {cid: r["document_id"] for cid, r in chunk_rows.items()}

    conflicts = detect_conflicts(
        result.sentences, chunk_document, {d: r["series"] for d, r in doc_rows.items()}
    )
    sentences = without_preference(result.sentences) if conflicts else result.sentences
    if not sentences:
        return None, {}

    def cite(chunk_id: int, start: int, end: int, quote: str) -> Citation:
        return _citation(chunk_id, start, end, quote, chunk_rows)

    used_docs = list(
        dict.fromkeys(chunk_document[q.passage_id] for s in sentences for q in s.quotes)
    )
    first_chunk: dict[str, int] = {}
    for s in sentences:
        for q in s.quotes:
            first_chunk.setdefault(chunk_document[q.passage_id], q.passage_id)
    response = AssistantResponse(
        output="B",
        lang=lang,
        notice=message("M7", lang) if conflicts else None,
        sentences=[
            Sentence(
                text=s.text,
                citations=[cite(q.passage_id, q.start, q.end, q.text) for q in s.quotes],
            )
            for s in sentences
        ],
        conflicts=[
            ConflictOut(
                fact_key=c.fact_key,
                values=[
                    ConflictValueOut(
                        document_id=v.document_id,
                        value=v.value,
                        citation=cite(v.quote.passage_id, v.quote.start, v.quote.end, v.quote.text),
                    )
                    for v in c.values
                ],
            )
            for c in conflicts
        ],
        documents=_cards(conn, used_docs, lang, first_chunk),
        disclaimer=message("M8", lang),
    )
    return response, {"validation_dropped": result.dropped, "regenerated": result.regenerated}
