"""Passage reranking. Cohere rerank-v3.5 when a key is set, otherwise term coverage.

Both return one score per passage in input order. The two scales differ, so the relevance
threshold is chosen per provider (config.RERANK_THRESHOLD_*).
"""

from functools import cache

import cohere
import httpx

from app.config import (
    DOCUMENT_THRESHOLD_LIVE,
    DOCUMENT_THRESHOLD_OFFLINE,
    RERANK_THRESHOLD_LIVE,
    RERANK_THRESHOLD_OFFLINE,
    settings,
)
from app.llm import LLMUnavailable
from app.text.terms import coverage, terms


@cache
def _client() -> cohere.ClientV2:
    # Calls normally take ~0.4 s but occasionally stall; a short timeout plus the SDK's
    # retries turns a stall into a quick retry instead of a hung request.
    return cohere.ClientV2(api_key=settings.cohere_api_key, timeout=5)


def threshold() -> float:
    return RERANK_THRESHOLD_LIVE if settings.use_live_cohere() else RERANK_THRESHOLD_OFFLINE


def document_threshold() -> float:
    return DOCUMENT_THRESHOLD_LIVE if settings.use_live_cohere() else DOCUMENT_THRESHOLD_OFFLINE


def rerank(query: str, passages: list[str]) -> list[float]:
    if not passages:
        return []
    if settings.use_live_cohere():
        try:
            response = _client().rerank(
                model=settings.rerank_model,
                query=query,
                documents=passages,
                top_n=len(passages),
                request_options={"max_retries": 3},
            )
        except (cohere.errors.TooManyRequestsError, httpx.TimeoutException) as exc:
            raise LLMUnavailable("rerank provider unavailable") from exc  # shown as M3
        scores = [0.0] * len(passages)
        for result in response.results:
            scores[result.index] = result.relevance_score
        return scores
    query_terms = terms(query)
    return [coverage(query_terms, set(terms(p))) for p in passages]
