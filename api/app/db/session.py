from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

Conn = psycopg.Connection[DictRow]

_pool: ConnectionPool[Conn] | None = None


def _configure(conn: Conn) -> None:
    register_vector(conn)


def pool() -> ConnectionPool[Conn]:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings.database_url,
            connection_class=Conn,
            min_size=1,
            max_size=10,
            # prepare_threshold=None: no server-side prepared statements, which a
            # transaction-mode pooler (Neon, PgBouncer) cannot route between backends.
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            configure=_configure,
            open=True,
        )
    return _pool


@contextmanager
def as_user(user_id: UUID | None) -> Iterator[Conn]:
    """A transaction in which RLS sees `user_id` as the caller.

    set_config(..., true) is transaction-local, so the identity cannot leak to the next
    request that borrows this pooled connection. user_id=None is for unauthenticated work
    (login, session lookup); the policies then return no documents.
    """
    with pool().connection() as conn, conn.transaction():
        conn.execute(
            "SELECT set_config('app.user_id', %s, true)",
            (str(user_id) if user_id else "",),
        )
        yield conn


@contextmanager
def as_owner() -> Iterator[Conn]:
    """Owner connection for migrations, seeding and ingestion. Never used by a request."""
    with psycopg.connect(settings.owner_database_url, row_factory=dict_row) as conn:
        yield conn


SQL_DIR = Path(__file__).parent


def migrate(conn: Conn) -> None:
    """Drop and recreate everything, then register the vector type on this connection."""
    conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
    conn.execute("CREATE SCHEMA public")
    conn.execute((SQL_DIR / "schema.sql").read_text())
    register_vector(conn)
    conn.execute((SQL_DIR / "rls.sql").read_text())
