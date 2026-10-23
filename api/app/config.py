from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # The API connects as `ems_app`: no BYPASSRLS, not the table owner. Migrations and
    # seeding use the owner connection and never run in the request path.
    database_url: str = "postgresql://ems_app:ems_app@localhost:5433/ems"
    owner_database_url: str = "postgresql://ems_owner:ems_owner@localhost:5433/ems"

    anthropic_api_key: str = ""
    cohere_api_key: str = ""
    gemini_api_key: str = ""
    # "auto" uses Claude/Cohere when the key is present and the offline provider otherwise.
    provider: Literal["auto", "live", "offline"] = "auto"

    # Language model providers, tried in this order (app/llm.py); unconfigured ones are
    # skipped. Gemini first, Cohere Command A on the same key as search as the fallback.
    llm_providers: str = "gemini,cohere,anthropic"
    gemini_fast_model: str = "gemini-2.5-flash"
    gemini_writer_model: str = "gemini-2.5-flash"
    cohere_chat_model: str = "command-a-03-2025"
    # Grading and extraction are on the M1 latency path, so on Claude they use the faster
    # model with thinking off; writing the Output B answer gets the stronger one.
    llm_fast_model: str = "claude-sonnet-5-5"
    llm_writer_model: str = "claude-opus-5-5"
    # embed-v4.0 stalled on about one call in eight (10 s+); v3.0 answered every call in
    # under 0.6 s. Same 1024 dimensions.
    embed_model: str = "embed-multilingual-v3.0"
    rerank_model: str = "rerank-v3.5"

    storage_dir: Path = REPO_ROOT / "seed" / "corpus"  # read by the ingester only
    # Ships inside the API package so a deployed function needs nothing from seed/.
    permission_matrix_path: Path = Path(__file__).parent / "auth" / "permission_matrix.yaml"

    session_secure_cookie: bool = False

    def use_live_llm(self) -> bool:
        any_key = bool(self.gemini_api_key or self.cohere_api_key or self.anthropic_api_key)
        return self.provider == "live" or (self.provider == "auto" and any_key)

    def use_live_cohere(self) -> bool:
        return self.provider == "live" or (self.provider == "auto" and bool(self.cohere_api_key))


settings = Settings()

EMBEDDING_DIM = 1024  # embed-multilingual-v3.0; the offline hasher uses the same width

# Retrieval
FTS_CANDIDATES = 50
VECTOR_CANDIDATES = 50
RRF_K = 60  # Cormack et al. 2009; smaller k lets one lexical hit dominate short Arabic queries
RERANK_TOP_N = 20
# Cohere rerank-v3.5 scores are calibrated per query; 0.30 kept every golden answerable
# query and rejected all below-threshold probes in eval/golden_assistant.yaml.
RERANK_THRESHOLD_LIVE = 0.30
# Output A/D from passage search alone (no title or metadata match) needs a stronger score:
# at 0.30 "the board memo" found an unrelated memo for a user who cannot see the board memo.
DOCUMENT_THRESHOLD_LIVE = 0.50
DOCUMENT_THRESHOLD_OFFLINE = 0.75
# Offline reranker is term coverage in [0, 1]. 0.6 means two of three query terms, or
# three of four; at 0.5 a year plus the event name matched almost every document.
RERANK_THRESHOLD_OFFLINE = 0.6
METADATA_HIT_SCORE = 1.0  # documents found by an exact metadata plan outrank any passage score

# Grading (SRS 1.6.12): the top two grade scores closer than this means the query is ambiguous.
GRADE_GAP = 0.15

# M1 (SRS 1.5.4): every M1 response is held until this many seconds after the request
# started, so "does not exist", "no access", "below threshold" and "not indexed" take the
# same time. Set above the slowest path that can end in M1 (grade + retrieve + rerank):
# usually 3 to 6 s live, but a 9.3 s grade was seen, and a path that overruns the floor
# would reveal its cause by timing. Trade-off: every M1 waits this long.
M1_LATENCY_FLOOR_S = 10.0
M1_LATENCY_FLOOR_OFFLINE_S = 0.6

MAX_QUERY_CHARS = 2000  # beyond this the request gets M5
RATE_LIMIT_PER_MINUTE = 20  # per user; the 21st request in a rolling minute gets 429 + M6

DECIMAL_PRECISION = 50
