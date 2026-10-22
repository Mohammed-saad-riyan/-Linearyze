from fastapi.testclient import TestClient

from app.assistant.grade import apply_rules, is_payment_request
from app.assistant.grade_types import Filters, GradeResult, Scores
from app.assistant.messages import message
from app.assistant.outputs import order_documents, select_output

MINISTRY_EN = (
    "Give me the letter from the Ministry of Exhibitions and Heritage that we "
    "received on the day we submitted the Exhibition Permit Application."
)
MINISTRY_AR = (
    "أعطني الخطاب الوارد من وزارة المعارض والتراث في اليوم الذي قدمنا فيه طلب تصريح المعرض"
)


def ask(client: TestClient, query: str) -> dict:  # type: ignore[type-arg]
    response = client.post("/api/assistant/query", json={"query": query, "debug": True})
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


def test_1_14_9_ministry_example_ranks_first(employee: TestClient) -> None:
    body = ask(employee, MINISTRY_EN)
    assert body["output"] == "A"
    assert [d["id"] for d in body["documents"]] == ["LTR-MEH-0317"]
    assert body["documents"][0]["date"] == "2026-03-17"


def test_1_14_9_ministry_example_in_arabic(employee: TestClient) -> None:
    body = ask(employee, MINISTRY_AR)
    assert body["output"] == "A"
    assert [d["id"] for d in body["documents"]] == ["LTR-MEH-0317"]
    assert body["lang"] == "ar"


def test_1_14_9_ministry_alias_from_the_srs(employee: TestClient) -> None:
    body = ask(
        employee,
        "Give me the letter from Ministry A that we received on the day "
        "we submitted the exhibition permit application",
    )
    assert [d["id"] for d in body["documents"]] == ["LTR-MEH-0317"]


def test_1_8_2_13_conflict_shows_m7_first(management: TestClient) -> None:
    body = ask(management, "What are the payment terms for Sadu Furnishings?")
    assert body["output"] == "B"
    assert body["notice"] == message("M7", "en")
    values = {v["document_id"]: v for c in body["conflicts"] for v in c["values"]}
    assert set(values) == {"CTR-SADU-014", "CTR-SADU-SO-031"}
    assert "30 days" in values["CTR-SADU-014"]["citation"]["quote"]
    assert "45 days" in values["CTR-SADU-SO-031"]["citation"]["quote"]


def test_1_8_2_9_quotes_are_verbatim_slices_of_the_source(management: TestClient) -> None:
    body = ask(management, "What are the payment terms for Sadu Furnishings?")
    for sentence in body["sentences"]:
        for citation in sentence["citations"]:
            passage = management.get(
                f"/api/documents/{citation['document_id']}/passages/{citation['chunk_id']}"
            ).json()
            text = next(
                p["text_original"] for p in passage["passages"] if p["id"] == citation["chunk_id"]
            )
            assert text[citation["start"] : citation["end"]] == citation["quote"]


def test_1_8_2_m8_on_every_output_b(management: TestClient) -> None:
    body = ask(management, "When does visitor registration open?")
    assert body["output"] == "B"
    assert body["disclaimer"] == message("M8", "en")
    assert body["documents"], "every document used gets a card (1.8.2.7)"


def test_1_2_12_latest_version_only(management: TestClient) -> None:
    body = ask(management, "Show me the booth price list")
    assert [d["id"] for d in body["documents"]] == ["PRC-2026-V2"]


def test_1_2_13_earlier_version_on_request(management: TestClient) -> None:
    body = ask(management, "Show me version 1 of the booth price list")
    assert [d["id"] for d in body["documents"]] == ["PRC-2026-V1"]


def test_1_8_4_5_document_list_is_deterministic(management: TestClient) -> None:
    runs = [ask(management, "Show me the exhibitor agreement") for _ in range(5)]
    orders = {tuple(d["id"] for d in r["documents"]) for r in runs}
    assert orders == {("CTR-QAMAR-022", "CTR-SADU-014")}
    assert all(r["output"] == "D" for r in runs)


def test_1_8_4_3_order_relevance_then_newest_then_id() -> None:
    import datetime as dt

    hits = [
        ("B", 0.9, dt.date(2026, 1, 1)),
        ("A", 0.9, dt.date(2026, 1, 1)),
        ("C", 0.9, dt.date(2026, 3, 1)),
        ("D", 1.0, None),
    ]
    assert order_documents(hits) == ["D", "C", "A", "B"]


def test_0_10_7_payment_request_refused(employee: TestClient) -> None:
    body = ask(employee, "Pay the Qamar Lighting invoice today")
    assert body == {
        "output": "E",
        "lang": "en",
        "message_id": "PAYMENT",
        "message": message("PAYMENT", "en"),
    }


def test_1_6_11_question_about_payment_terms_is_not_a_payment() -> None:
    assert not is_payment_request("When do we have to pay the Qamar invoice?")
    assert is_payment_request("Transfer SAR 50,000 to Qamar Lighting")
    assert is_payment_request("ادفع فاتورة قمر للإضاءة")


def _graded(**scores: float) -> GradeResult:
    return GradeResult(
        scores=Scores(**scores), requests=["one"], filters=Filters(), query_en="q", query_ar="q"
    )


def test_1_6_12_close_scores_are_ambiguous() -> None:
    assert apply_rules(_graded(DR=0.55, IR=0.5), "q").grade == "AM"
    assert apply_rules(_graded(DR=0.9, IR=0.1), "q").grade == "DR"


def test_1_6_14_two_requests_are_ambiguous(employee: TestClient) -> None:
    graded = _graded(DR=0.9)
    graded.requests = ["the price list", "the cost sheet"]
    assert apply_rules(graded, "q").grade == "AM"
    body = ask(employee, "Send me the price list and also the cost sheet")
    assert body["output"] == "C"
    assert len(body["options"]) <= 6 and body["options"][-1] == "Something else"


def test_1_7_1_output_selection_table() -> None:
    def pick(grade: str, docs: int = 0, passages: int = 0, impossible: bool = False) -> tuple:  # type: ignore[type-arg]
        s = select_output(
            grade,
            payment_request=False,
            plan_impossible=impossible,  # type: ignore[arg-type]
            document_count=docs,
            passage_count=passages,
        )
        return s.output, s.message_id

    assert pick("DR", docs=0) == ("E", "M1")
    assert pick("DR", docs=1) == ("A", None)
    assert pick("DR", docs=3) == ("D", None)
    assert pick("IR", passages=0) == ("E", "M1")
    assert pick("IR", passages=2) == ("B", None)
    assert pick("DR", docs=1, impossible=True) == ("E", "M1")
    assert pick("AM") == ("C", None)
    assert pick("OT") == ("E", "M2")


def test_1_3_7_injection_document_is_inert(employee: TestClient) -> None:
    body = ask(employee, "How many badge cards were ordered for visitor badge printing?")
    text = str(body)
    assert "CANARY" not in text
    assert "Board Memo" not in text and "Salary Bands" not in text


def test_m5_long_query(employee: TestClient) -> None:
    response = employee.post("/api/assistant/query", json={"query": "x" * 2001})
    assert response.status_code == 413
    assert response.json()["message_id"] == "M5"


def test_1_3_9_rate_limit_returns_429_with_m6(employee: TestClient) -> None:
    from app.config import RATE_LIMIT_PER_MINUTE

    for _ in range(RATE_LIMIT_PER_MINUTE):
        employee.post("/api/assistant/query", json={"query": "Pay the invoice"})
    response = employee.post("/api/assistant/query", json={"query": "Pay the invoice"})
    assert response.status_code == 429
    assert response.json()["message_id"] == "M6"
