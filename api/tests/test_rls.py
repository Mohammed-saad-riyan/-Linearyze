"""Row-level security (SRS 0.10.1, 1.3.2, 0.9.2.2, 0.7.8).

These tests query as the application role, the same way the API does. If a policy were
missing, the rows would come back here, before any Python filtering could hide them.
"""

from uuid import UUID

import pytest
import yaml
from fastapi.testclient import TestClient

from app.config import REPO_ROOT
from app.db.session import as_owner, as_user

MANIFEST = yaml.safe_load((REPO_ROOT / "seed" / "corpus_manifest.yaml").read_text())["documents"]
CANARIES = {d["id"]: d["canary"] for d in MANIFEST if "canary" in d}
CONFIDENTIAL = {d["id"] for d in MANIFEST if d["confidentiality"] == "confidential"}
OUT_OF_SCOPE = {d["id"] for d in MANIFEST if d.get("event") == "HERITAGE26"}


def _visible(user_id: UUID | None, sql: str) -> set[str]:
    with as_user(user_id) as conn:
        return {r["id"] for r in conn.execute(sql)}


def test_api_role_cannot_bypass_rls() -> None:
    with as_user(None) as conn:
        row = conn.execute(
            "SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        owner = conn.execute(
            "SELECT tableowner FROM pg_tables WHERE tablename = 'documents'"
        ).fetchone()
        me = conn.execute("SELECT current_user AS u").fetchone()
    assert row == {"rolbypassrls": False, "rolsuper": False}
    assert owner["tableowner"] != me["u"]


def test_1_3_2_rls_hides_confidential(user_ids: dict[str, UUID]) -> None:
    visible = _visible(user_ids["employee"], "SELECT id FROM documents")
    assert visible.isdisjoint(CONFIDENTIAL)
    assert _visible(user_ids["management"], "SELECT id FROM documents") >= CONFIDENTIAL


def test_0_9_2_2_employee_scope(user_ids: dict[str, UUID]) -> None:
    visible = _visible(user_ids["employee"], "SELECT DISTINCT document_id AS id FROM chunks")
    assert visible.isdisjoint(OUT_OF_SCOPE)
    assert visible  # the employee does see their own event


@pytest.mark.parametrize("canary", sorted(CANARIES.values()))
def test_1_3_2_canary_unreachable_through_fulltext_and_vectors(
    canary: str, user_ids: dict[str, UUID]
) -> None:
    with as_user(user_ids["employee"]) as conn:
        by_text = conn.execute(
            "SELECT count(*) AS n FROM chunks WHERE text_original LIKE %s", (f"%{canary}%",)
        ).fetchone()["n"]
        by_vector = conn.execute(
            "SELECT count(*) AS n FROM (SELECT text_original FROM chunks"
            " ORDER BY embedding <=> (SELECT embedding FROM chunks LIMIT 1) LIMIT 1000) x"
            " WHERE text_original LIKE %s",
            (f"%{canary}%",),
        ).fetchone()["n"]
    assert by_text == 0
    assert by_vector == 0


def test_0_7_5_admin_reads_no_documents(user_ids: dict[str, UUID]) -> None:
    assert _visible(user_ids["admin"], "SELECT id FROM documents") == set()
    assert _visible(user_ids["admin"], "SELECT id::text FROM chunks") == set()


def test_no_identity_reads_no_documents() -> None:
    assert _visible(None, "SELECT id FROM documents") == set()


def test_0_7_8_scope_change_applies_to_the_next_request(
    employee: TestClient, user_ids: dict[str, UUID]
) -> None:
    query = {"query": "Give me the Venue Rental Agreement - Najd Heritage Festival"}
    assert employee.post("/api/assistant/query", json=query).json()["output"] == "E"
    with as_owner() as conn:
        conn.execute("INSERT INTO user_scopes VALUES (%s, 'HERITAGE26')", (user_ids["employee"],))
    try:
        body = employee.post("/api/assistant/query", json=query).json()
        assert body["output"] == "A"
        assert body["documents"][0]["id"] == "HRT-VENUE"
    finally:
        with as_owner() as conn:
            conn.execute(
                "DELETE FROM user_scopes WHERE user_id = %s AND event_id = 'HERITAGE26'",
                (user_ids["employee"],),
            )


def test_1_12_audit_log_has_no_query_text(employee: TestClient) -> None:
    employee.post("/api/assistant/query", json={"query": "When does visitor registration open?"})
    with as_owner() as conn:
        columns = {
            r["column_name"]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'audit_log'"
            )
        }
        last = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    assert not columns & {"query", "query_text", "answer", "prompt"}
    assert "registration" not in str(last).lower()
