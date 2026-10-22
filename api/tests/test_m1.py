"""M1 is identical in every way, whatever the cause (SRS 1.5.4, 0.10.3)."""

import statistics
import time

from fastapi.testclient import TestClient

from app.assistant.messages import message
from app.config import M1_LATENCY_FLOOR_OFFLINE_S

# One employee query per cause. Each document named here is in seed/corpus_manifest.yaml.
FOUR_CAUSES = {
    "does_not_exist": "Give me the Riyadh Marathon sponsorship contract",
    "no_access": "Give me the Board Memo - Executive Bonus Pool 2026",  # confidential
    "below_threshold": "What colour are the volunteer uniforms?",
    "not_yet_indexed": "Give me the sponsorship proposal",  # PND-SPONSOR, indexed_at NULL
}
TIMING_TOLERANCE_S = 0.15


def _ask(client: TestClient, query: str) -> tuple[bytes, dict[str, str], float]:
    started = time.perf_counter()
    response = client.post("/api/assistant/query", json={"query": query, "debug": True})
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    return response.content, dict(response.headers), elapsed


def test_1_5_4_m1_byte_identical_four_causes(employee: TestClient) -> None:
    bodies = {cause: _ask(employee, q)[0] for cause, q in FOUR_CAUSES.items()}
    assert len(set(bodies.values())) == 1, bodies
    assert b'"message_id":"M1"' in bodies["no_access"]


def test_1_5_4_m1_headers_identical(employee: TestClient) -> None:
    headers = [_ask(employee, q)[1] for q in FOUR_CAUSES.values()]
    comparable = [{k: v for k, v in h.items() if k != "date"} for h in headers]
    assert all(h == comparable[0] for h in comparable)


def test_1_5_4_m1_timing_within_tolerance(employee: TestClient) -> None:
    samples: dict[str, list[float]] = {cause: [] for cause in FOUR_CAUSES}
    for _ in range(3):
        for cause, query in FOUR_CAUSES.items():
            samples[cause].append(_ask(employee, query)[2])
    medians = {cause: statistics.median(times) for cause, times in samples.items()}
    assert max(medians.values()) - min(medians.values()) < TIMING_TOLERANCE_S, medians
    assert min(medians.values()) >= M1_LATENCY_FLOOR_OFFLINE_S


def test_0_10_3_m1_has_no_title_snippet_or_count(employee: TestClient) -> None:
    body = _ask(employee, FOUR_CAUSES["no_access"])[0].decode()
    assert "Bonus" not in body and "CANARY" not in body and "Board" not in body
    assert body == (
        '{"output":"E","lang":"en","message_id":"M1","message":"' + message("M1", "en") + '"}'
    )


def test_1_5_4_debug_flag_adds_nothing_to_m1(employee: TestClient) -> None:
    with_debug = employee.post(
        "/api/assistant/query", json={"query": FOUR_CAUSES["no_access"], "debug": True}
    ).content
    without = employee.post(
        "/api/assistant/query", json={"query": FOUR_CAUSES["no_access"]}
    ).content
    assert with_debug == without


def test_management_gets_the_document_the_employee_cannot(management: TestClient) -> None:
    body = management.post("/api/assistant/query", json={"query": FOUR_CAUSES["no_access"]}).json()
    assert body["output"] == "A"
    assert body["documents"][0]["id"] == "CONF-BONUS"
