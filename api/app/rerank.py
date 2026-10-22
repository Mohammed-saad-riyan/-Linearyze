"""Passage reranking. Cohere rerank-v3.5 when a key is set, otherwise term coverage.

Both return one score per passage in input order. The two scales differ, so the relevance
threshold is chosen per provider (config.RERANK_THRESHOLD_*).
"""

from functools import cache

import cohere

from app.config import RERANK_THRESHOLD_LIVE, RERANK_THRESHOLD_OFFLINE, settings
from app.text.terms import coverage, terms


@cache
def _client() -> cohere.ClientV2:
    return cohere.ClientV2(api_key=settings.cohere_api_key)


def threshold() -> float:
    return RERANK_THRESHOLD_LIVE if settings.use_live_cohere() else RERANK_THRESHOLD_OFFLINE


def rerank(query: str, passages: list[str]) -> list[float]:
    if not passages:
        return []
    if settings.use_live_cohere():
        response = _client().rerank(
            model=settings.rerank_model, query=query, documents=passages, top_n=len(passages)
        )
        scores = [0.0] * len(passages)
        for result in response.results:
            scores[result.index] = result.relevance_score
        return scores
    query_terms = terms(query)
    return [coverage(query_terms, set(terms(p))) for p in passages]
