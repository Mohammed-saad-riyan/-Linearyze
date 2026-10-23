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


def test_0_8_22_changing_a_cell_changes_access_without_code(tmp_path) -> None:  # type: ignore[no-untyped-def]
    edited = tmp_path / "matrix.yaml"
    edited.write_text(
        settings.permission_matrix_path.read_text().replace(
            "management: Y,   employee: Y,   admin: N}",
            "management: Y,   employee: N,   admin: N}",
            1,
        )
    )
    assert matrix().allows("employee", "0.8.1")
    assert not load_matrix(edited).allows("employee", "0.8.1")


def test_0_8_matrix_cells_match_the_srs_table() -> None:
    m = matrix()
    assert [m.cell(r, "0.8.2") for r in ROLES] == ["Y", "TBD", "N"]
    assert [m.cell(r, "0.8.17") for r in ROLES] == ["N", "N", "Y"]
    assert [m.cell(r, "0.8.21") for r in ROLES] == ["Y", "N", "N"]


def test_tbd_cells_are_denied_unless_the_poc_decided_them() -> None:
    m = matrix()
    assert m.cell("admin", "0.8.3") == "TBD" and not m.allows("admin", "0.8.3")
    assert m.cell("employee", "0.8.2") == "TBD" and m.allows("employee", "0.8.2")


def test_poc_decision_cannot_overrule_a_decided_cell(tmp_path) -> None:  # type: ignore[no-untyped-def]
    edited = tmp_path / "matrix.yaml"
    edited.write_text(
        settings.permission_matrix_path.read_text().replace(
            '"0.8.2": {employee: Y}', '"0.8.2": {admin: Y}'
        )
    )
    with pytest.raises(ValueError, match="not TBD"):
        load_matrix(edited)


def test_0_7_5_management_cannot_manage_users(management: TestClient) -> None:
    assert management.get("/api/admin/users").status_code == 403


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


def test_0_7_7_no_session_is_401() -> None:
    response = TestClient(real_app).post("/api/assistant/query", json={"query": "x"})
    assert response.status_code == 401
