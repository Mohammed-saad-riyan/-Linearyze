import hashlib

from fastapi.testclient import TestClient

from app.config import settings
from app.ingest.parsers import parse


def test_1_9_3_download_returns_the_original_bytes(management: TestClient) -> None:
    response = management.get("/api/documents/LTR-MEH-0317/download")
    assert response.status_code == 200
    original = settings.storage_dir / "letters/MEH_Eid_Operating_Hours_Circular_2026-03-17.pdf"
    assert (
        hashlib.sha256(response.content).digest() == hashlib.sha256(original.read_bytes()).digest()
    )


def test_1_9_3_download_of_unreadable_document_is_404(employee: TestClient) -> None:
    hidden = employee.get("/api/documents/CONF-BONUS/download")
    missing = employee.get("/api/documents/NO-SUCH-DOC/download")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.content == missing.content


def test_1_2_pdf_arabic_comes_out_in_reading_order() -> None:
    passages = parse(settings.storage_dir / "letters/MEH_Floor_Plan_Comments_2026-03-03.pdf")
    text = "\n".join(p.text for p in passages)
    assert "الرقم: و م ت/ف/٢٠٢٦/٠٣١٢" in text  # digits not reversed
    assert "بـ ٣٥٠٠ زائر" in text
    assert all(p.page == 1 for p in passages)


def test_1_9_7_excel_passages_carry_sheet_and_range() -> None:
    passages = parse(settings.storage_dir / "pricing/v2/Booth_Price_List_2026.xlsx")
    row = next(p for p in passages if "Standard booth" in p.text)
    assert row.sheet == "Booths" and row.cell_range == "A4:D7"
    assert "12,000" in row.text


def test_1_9_6_word_passages_carry_their_heading() -> None:
    passages = parse(settings.storage_dir / "finance/Expo_2026_Revenue_Summary.docx")
    confirmed = next(p for p in passages if "768,000" in p.text)
    assert confirmed.heading == "Confirmed revenue / الإيرادات المؤكدة"


def test_view_returns_the_cited_passage(employee: TestClient) -> None:
    body = employee.post(
        "/api/assistant/query", json={"query": "When does visitor registration open?"}
    ).json()
    citation = body["sentences"][0]["citations"][0]
    view = employee.get(f"/api/documents/{citation['document_id']}/passages/{citation['chunk_id']}")
    assert view.status_code == 200
    assert any(p["id"] == citation["chunk_id"] for p in view.json()["passages"])
