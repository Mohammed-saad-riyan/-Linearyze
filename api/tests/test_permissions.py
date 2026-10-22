from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.permissions import ROLES, load_matrix, matrix
from app.auth.sessions import CurrentUser, require
from app.config import settings
from app.main import app as real_app

# One route per capability, guarded exactly as production routes are, so every cell of the
# matrix is exercised through the real session and require() path (SRS 0.8.23).
probe = FastAPI()
for _capability in matrix().capabilities:

    def _route(user: Annotated[CurrentUser, Depends(require(_capability))]) -> dict[str, str]:
        return {"role": user.role}

    probe.get(f"/probe/{_capability}")(_route)

CELLS = [(cap, role) for cap in matrix().capabilities for role in ROLES]


def test_0_8_22_matrix_has_21_capabilities_and_3_roles() -> None:
    assert len(matrix().capabilities) == 21
    assert len(CELLS) == 63


@pytest.mark.parametrize(("capability", "role"), CELLS)
def test_0_8_23_permission_matrix(capability: str, role: str, login) -> None:  # type: ignore[no-untyped-def]
    session = login(role)
    client = TestClient(probe, cookies=session.cookies)
    response = client.get(f"/probe/{capability}")
    expected = 200 if matrix().allows(role, capability) else 403  # type: ignore[arg-type]
    assert response.status_code == expected
    if expected == 403:
        assert response.json()["detail"] == {"message_id": "M10"}


def test_0_8_22_matrix_with_a_missing_cell_fails_at_load(tmp_path) -> None:  # type: ignore[no-untyped-def]
    broken = tmp_path / "matrix.yaml"
    broken.write_text(
        settings.permission_matrix_path.read_text().replace(
            "search_assistant:          {management: allow, employee: allow, admin: deny}",
            "search_assistant:          {management: allow, employee: allow}",
        )
    )
    with pytest.raises(ValueError, match="search_assistant"):
        load_matrix(broken)


def test_0_7_5_admin_cannot_call_assistant(admin: TestClient) -> None:
    response = admin.post("/api/assistant/query", json={"query": "Exhibitor Agreement"})
    assert response.status_code == 403


def test_2_2_3_admin_cannot_call_advisor(admin: TestClient) -> None:
    response = admin.post("/api/advisor/query", json={"query": "profit = revenue - cost"})
    assert response.status_code == 403


def test_0_7_5_admin_cannot_download_documents(admin: TestClient) -> None:
    assert admin.get("/api/documents/CTR-SADU-014/download").status_code == 403


def test_admin_can_list_users_and_others_cannot(admin: TestClient, management: TestClient) -> None:
    assert admin.get("/api/admin/users").status_code == 200
    assert management.get("/api/admin/users").status_code == 403


def test_no_session_is_401_with_m9() -> None:
    response = TestClient(real_app).post("/api/assistant/query", json={"query": "x"})
    assert response.status_code == 401
    assert response.json()["detail"] == {"message_id": "M9"}
