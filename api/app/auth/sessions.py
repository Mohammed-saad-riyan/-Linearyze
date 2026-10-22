import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException

from app.auth.permissions import Role, matrix
from app.db.session import as_user

SESSION_COOKIE = "ems_session"  # current_user() reads it via its parameter name
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    _, salt_hex, digest_hex = stored.split("$")
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str
    name: str
    role: Role
    event_ids: tuple[str, ...]


def login(email: str, password: str) -> str | None:
    with as_user(None) as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = %s AND active", (email,)
        ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id) VALUES (%s, %s)",
            (_token_hash(token), row["id"]),
        )
        return token


def logout(token: str) -> None:
    with as_user(None) as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at = now() WHERE token_hash = %s", (_token_hash(token),)
        )


def resolve(token: str) -> CurrentUser | None:
    # Role and scope are read from the database on every request rather than cached in
    # the session, so a role change or deactivation applies to the next request (SRS 0.7.8).
    with as_user(None) as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, u.name, u.role,
                   coalesce(array_agg(s.event_id ORDER BY s.event_id)
                            FILTER (WHERE s.event_id IS NOT NULL), '{}') AS event_ids
            FROM sessions t
            JOIN users u ON u.id = t.user_id
            LEFT JOIN user_scopes s ON s.user_id = u.id
            WHERE t.token_hash = %s AND t.revoked_at IS NULL AND u.active
            GROUP BY u.id
            """,
            (_token_hash(token),),
        ).fetchone()
    if row is None:
        return None
    return CurrentUser(row["id"], row["email"], row["name"], row["role"], tuple(row["event_ids"]))


def current_user(ems_session: str | None = Cookie(default=None)) -> CurrentUser:
    user = resolve(ems_session) if ems_session else None
    if user is None:
        raise HTTPException(status_code=401, detail={"message_id": "M9"})
    return user


def require(capability: str):  # type: ignore[no-untyped-def]
    """FastAPI dependency: 403 with M10 unless the permission matrix allows the capability."""
    if capability not in matrix().capabilities:
        raise KeyError(f"unknown capability {capability!r}")

    def check(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if not matrix().allows(user.role, capability):
            raise HTTPException(status_code=403, detail={"message_id": "M10"})
        return user

    return check
