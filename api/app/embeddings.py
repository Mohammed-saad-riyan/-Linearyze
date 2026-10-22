"""Text embeddings. Cohere embed-v4.0 (multilingual) when a key is set, otherwise a
deterministic feature hasher so tests and CI run without network access.

The hasher has no cross-lingual ability: an English query will not find an Arabic-only
passage through it. docs/EVAL_REPORT.md reports offline and live numbers separately.
"""

import hashlib
from functools import cache

import cohere
import numpy as np

from app.config import EMBEDDING_DIM, settings
from app.text.arabic import normalize
from app.text.terms import terms

_BATCH = 96  # Cohere's maximum texts per embed call


@cache
def _client() -> cohere.ClientV2:
    return cohere.ClientV2(api_key=settings.cohere_api_key)


def _live(texts: list[str], input_type: str) -> list[np.ndarray]:
    vectors: list[np.ndarray] = []
    for start in range(0, len(texts), _BATCH):
        response = _client().embed(
            model=settings.embed_model,
            texts=texts[start : start + _BATCH],
            input_type=input_type,
            embedding_types=["float"],
            output_dimension=EMBEDDING_DIM,
        )
        floats = response.embeddings.float_ or []
        vectors.extend(np.asarray(v, dtype=np.float32) for v in floats)
    return vectors


def _hash_features(text: str) -> np.ndarray:
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    features = terms(text)
    # Character trigrams of the normalized text catch partial matches that whole-term
    # features miss (codes like "B-14", inflected Arabic forms the stemmer leaves alone).
    flat = normalize(text).replace(" ", "_")
    features += [flat[i : i + 3] for i in range(len(flat) - 2)]
    for feature in features:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % EMBEDDING_DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[index] += sign
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


def embed_documents(texts: list[str]) -> list[np.ndarray]:
    if settings.use_live_cohere():
        return _live(texts, "search_document")
    return [_hash_features(t) for t in texts]


def embed_query(text: str) -> np.ndarray:
    if settings.use_live_cohere():
        return _live([text], "search_query")[0]
    return _hash_features(text)
