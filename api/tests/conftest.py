"""Tests run against a real Postgres (docker compose up db) with the offline providers, so
they need no API keys and give the same result on every run."""

import os

os.environ["PROVIDER"] = "offline"

from collections.abc import Iterator  # noqa: E402
from uuid import UUID  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import as_owner, migrate  # noqa: E402
from app.ingest.index import ingest_corpus, seed_people  # noqa: E402
from app.main import app  # noqa: E402

PASSWORDS = {
    "management": ("management@demo.lnz", "demo-management"),
    "employee": ("employee@demo.lnz", "demo-employee"),
    "admin": ("admin@demo.lnz", "demo-admin"),
}


@pytest.fixture(scope="session", autouse=True)
def seeded_database() -> None:
    with as_owner() as conn:
        migrate(conn)
        seed_people(conn)
        ingest_corpus(conn)


@pytest.fixture(scope="session")
def user_ids() -> dict[str, UUID]:
    with as_owner() as conn:
        return {r["role"]: r["id"] for r in conn.execute("SELECT role, id FROM users")}


def _client(role: str) -> TestClient:
    client = TestClient(app)
    email, password = PASSWORDS[role]
    assert (
        client.post("/api/auth/login", json={"email": email, "password": password}).status_code
        == 200
    )
    return client


@pytest.fixture
def management() -> Iterator[TestClient]:
    yield _client("management")


@pytest.fixture
def employee() -> Iterator[TestClient]:
    yield _client("employee")


@pytest.fixture
def admin() -> Iterator[TestClient]:
    yield _client("admin")


@pytest.fixture
def login():  # type: ignore[no-untyped-def]
    return _client


@pytest.fixture(autouse=True)
def fresh_rate_limit() -> None:
    """Each test starts with an empty per-user window; test_rate_limit fills it on purpose."""
    from app import main

    main._recent.clear()
