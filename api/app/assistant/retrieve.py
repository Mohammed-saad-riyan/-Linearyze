"""Hybrid retrieval under row-level security (SRS 1.5.2, 1.6.4, 1.6.5).

Full-text and vector candidates are fetched by SQL that runs as the caller, so the
policies in db/rls.sql have already removed unreadable rows before anything is ranked.
Candidates are merged with reciprocal rank fusion, the top passages are reranked, and only
passages at or above the relevance threshold survive.
"""

from dataclasses import dataclass

import numpy as np

from app import rerank
from app.assistant.plan import TITLE_MATCH_COVERAGE, Plan, filter_sql
from app.config import (
    FTS_CANDIDATES,
    METADATA_HIT_SCORE,
    RERANK_TOP_N,
    RRF_K,
    VECTOR_CANDIDATES,
)
from app.db.session import Conn
from app.text.terms import coverage, or_tsquery, passage_context, terms


@dataclass
class PassageHit:
    chunk_id: int
    document_id: str
    text: str
    score: float  # reranker relevance
    page: int | None
    heading: str | None
    sheet: str | None
    cell_range: str | None


@dataclass
class DocumentHit:
    document_id: str
    score: float
    via: str  # "metadata", "title" or "passage", shown in the debug panel


def _rrf(*rankings: list[int]) -> list[int]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores, key=lambda cid: (-scores[cid], cid))


def search_passages(
    conn: Conn,
    plan: Plan,
    query: str,
    query_vector: np.ndarray,
    within: list[str] | None = None,
    rerank_passages: bool = True,
) -> list[PassageHit]:
    """Passages relevant to `query` that pass the threshold, best first.

    With rerank_passages=False the fused full-text + vector order is returned as is, with
    the RRF score, and no threshold: for callers that verify every passage they use.
    """
    where, params = filter_sql(plan)
    if within is not None:
        where += " AND d.id = ANY(%(within)s)"
        params["within"] = within

    lexical: list[int] = []
    tsquery = or_tsquery(query)
    if tsquery:
        lexical = [
            r["id"]
            for r in conn.execute(
                f"""
            SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE {where} AND c.tsv @@ to_tsquery('simple', %(q)s)
            ORDER BY ts_rank(c.tsv, to_tsquery('simple', %(q)s)) DESC, c.id
            LIMIT {FTS_CANDIDATES}
            """,
                {**params, "q": tsquery},
            ).fetchall()
        ]
    semantic = [
        r["id"]
        for r in conn.execute(
            f"""
        SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE {where}
        ORDER BY c.embedding <=> %(v)s, c.id
        LIMIT {VECTOR_CANDIDATES}
        """,
            {**params, "v": query_vector},
        ).fetchall()
    ]

    candidate_ids = _rrf(lexical, semantic)[:RERANK_TOP_N]
    if not candidate_ids:
        return []
    rows = {
        r["id"]: r
        for r in conn.execute(
            "SELECT c.id, c.document_id, c.text_original, c.page, c.heading, c.sheet, c.cell_range,"
            " d.title, d.title_alt FROM chunks c JOIN documents d ON d.id = c.document_id"
            " WHERE c.id = ANY(%s)",
            (candidate_ids,),
        ).fetchall()
    }
    ordered = [rows[cid] for cid in candidate_ids]
    if not rerank_passages:
        return [
            PassageHit(
                r["id"],
                r["document_id"],
                r["text_original"],
                1.0 / (RRF_K + rank + 1),
                r["page"],
                r["heading"],
                r["sheet"],
                r["cell_range"],
            )
            for rank, r in enumerate(ordered)
        ]
    texts = [
        passage_context(r["title"], r["title_alt"], r["heading"], r["text_original"])
        for r in ordered
    ]
    # The plan's English topic when the query is the plan's own topic; callers that search
    # for something else (an advisor term) pass their own query.
    rerank_query = plan.rerank_query if plan.rerank_query and query == plan.topic else query
    scores = rerank.rerank(rerank_query, texts)
    cutoff = rerank.threshold()
    hits = [
        PassageHit(
            r["id"],
            r["document_id"],
            r["text_original"],
            s,
            r["page"],
            r["heading"],
            r["sheet"],
            r["cell_range"],
        )
        for r, s in zip(ordered, scores, strict=True)
        if s >= cutoff
    ]
    hits.sort(key=lambda h: (-h.score, h.chunk_id))
    return hits


def _documents_by_filters(conn: Conn, plan: Plan) -> list[str]:
    where, params = filter_sql(plan)
    return [
        r["id"]
        for r in conn.execute(
            f"SELECT d.id FROM documents d WHERE {where} ORDER BY d.id", params
        ).fetchall()
    ]


def _documents_by_title(conn: Conn, plan: Plan, topic: str) -> list[DocumentHit]:
    tsquery = or_tsquery(topic)
    wanted = terms(topic)
    if tsquery is None or len(set(wanted)) < 2:
        return []
    where, params = filter_sql(plan)
    rows = conn.execute(
        f"SELECT d.id, d.title_terms FROM documents d "
        f"WHERE {where} AND d.title_tsv @@ to_tsquery('simple', %(q)s)",
        {**params, "q": tsquery},
    ).fetchall()
    hits = []
    for row in rows:
        if coverage(wanted, set(row["title_terms"].split())) >= TITLE_MATCH_COVERAGE:
            hits.append(DocumentHit(row["id"], METADATA_HIT_SCORE, "title"))
    return hits


def find_documents(
    conn: Conn, plan: Plan, topic: str, query_vector: np.ndarray
) -> list[DocumentHit]:
    """Documents that answer a DR query: none (M1), one (Output A) or several (Output D)."""
    if plan.has_strong_constraints:
        ids = _documents_by_filters(conn, plan)
        if len(ids) <= 1:
            return [DocumentHit(i, METADATA_HIT_SCORE, "metadata") for i in ids]
        # Several documents fit the filters; let the topic narrow them if it can.
        narrowed = search_passages(conn, plan, topic, query_vector, within=ids)
        if narrowed:
            return _best_per_document(narrowed, via="metadata+passage")
        return [DocumentHit(i, METADATA_HIT_SCORE, "metadata") for i in ids]

    by_title = _documents_by_title(conn, plan, topic)
    if by_title:
        return by_title
    # Handing over a whole document needs more than a passage that is merely on topic.
    floor = rerank.document_threshold()
    hits = [h for h in search_passages(conn, plan, topic, query_vector) if h.score >= floor]
    return _best_per_document(hits, via="passage")


def _best_per_document(hits: list[PassageHit], via: str) -> list[DocumentHit]:
    best: dict[str, float] = {}
    for hit in hits:
        best[hit.document_id] = max(best.get(hit.document_id, 0.0), hit.score)
    return [DocumentHit(doc_id, score, via) for doc_id, score in best.items()]
