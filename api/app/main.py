import datetime as dt
import logging
import math
import time
from collections import defaultdict, deque
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import llm
from app.advisor import pipeline as advisor
from app.assistant import pipeline as assistant
from app.assistant.messages import Lang, MessageId, message
from app.auth import sessions
from app.auth.permissions import matrix
from app.auth.sessions import SESSION_COOKIE, CurrentUser, current_user, require
from app.config import (
    M1_LATENCY_FLOOR_OFFLINE_S,
    M1_LATENCY_FLOOR_S,
    MAX_QUERY_CHARS,
    RATE_LIMIT_PER_MINUTE,
    settings,
)
from app.db.session import as_user
from app.text.arabic import detect_language

log = logging.getLogger("ems")

app = FastAPI(
    title="Linearyze EMS proof of concept", docs_url="/api/docs", openapi_url="/api/openapi.json"
)

# Demo "today". The corpus is set in spring 2026 and relative dates in questions are
# resolved against this, so answers do not drift as the calendar moves.
DEMO_TODAY = dt.date(2026, 5, 1)


def _lang(text: str) -> Lang:
    return "ar" if detect_language(text) == "ar" else "en"


def _message_response(
    message_id: MessageId, lang: Lang, status: int, **placeholders: int
) -> Response:
    return Response(
        assistant.render_message(message_id, lang, **placeholders),
        status_code=status,
        media_type="application/json",
    )


# --- auth -------------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginRequest, response: Response) -> dict[str, str]:
    token = sessions.login(body.email.strip().lower(), body.password)
    if token is None:
        raise HTTPException(status_code=401, detail={"error": "invalid_credentials"})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.session_secure_cookie,
        max_age=12 * 3600,
    )
    return {"status": "ok"}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        sessions.logout(token)
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "ok"}


@app.get("/api/auth/me")
def me(user: Annotated[CurrentUser, Depends(current_user)]) -> dict[str, Any]:
    allowed = [c for c in matrix().capabilities if matrix().allows(user.role, c)]
    return {
        "max_query_chars": MAX_QUERY_CHARS,  # the browser refuses longer queries (1.11.6)
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "events": list(user.event_ids),
        "capabilities": allowed,
    }


# --- rate limit (SRS 1.3.9) ---------------------------------------------------------------

_recent: dict[str, deque[float]] = defaultdict(deque)


def _seconds_until_allowed(user: CurrentUser) -> int:
    """0 if the user may query now, else whole seconds until the oldest request in the
    one-minute window expires ({n} in M6, SRS 1.7.3). In process: one API instance is
    enough for the PoC; several would keep this window in Postgres."""
    now = time.monotonic()
    window = _recent[str(user.id)]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_MINUTE:
        return max(1, math.ceil(60 - (now - window[0])))
    window.append(now)
    return 0


# --- assistant ----------------------------------------------------------------------------


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    debug: bool = False


def _audit(user: CurrentUser, action: str, result: str, **fields: Any) -> None:
    columns = ["user_id", "role", "action", "result", *fields]
    values = [user.id, user.role, action, result, *fields.values()]
    with as_user(user.id) as conn:
        conn.execute(
            f"INSERT INTO audit_log ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(values))})",
            values,
        )


def _hold_until(deadline: float) -> None:
    remaining = deadline - time.perf_counter()
    if remaining > 0:
        time.sleep(remaining)


@app.post("/api/assistant/query")
def assistant_query(
    body: QueryRequest, user: Annotated[CurrentUser, Depends(require("0.8.1"))]
) -> Response:
    started = time.perf_counter()
    lang = _lang(body.query)
    if len(body.query) > MAX_QUERY_CHARS:
        return _message_response("M5", lang, 413, max=MAX_QUERY_CHARS)
    if wait := _seconds_until_allowed(user):
        return _message_response("M6", lang, 429, n=wait)
    try:
        with as_user(user.id) as conn:
            outcome = assistant.run(conn, body.query, DEMO_TODAY, debug=body.debug)
    except llm.LLMTimeout as exc:
        log.warning("M4: %r caused by %r", exc, exc.__cause__)
        return _message_response("M4", lang, 504)
    except llm.LLMUnavailable as exc:
        log.warning("M3: %r caused by %r", exc, exc.__cause__)
        return _message_response("M3", lang, 503)

    if outcome.message_id == "M1":
        # SRS 1.5.4: every M1 leaves at the same moment after the request arrived, so the
        # four causes cannot be told apart by timing either.
        floor = M1_LATENCY_FLOOR_S if settings.use_live_llm() else M1_LATENCY_FLOOR_OFFLINE_S
        _hold_until(started + floor)
    latency_ms = int((time.perf_counter() - started) * 1000)
    _audit(
        user,
        "assistant.query",
        outcome.message_id or outcome.output,
        grade=outcome.grade,
        output_type=outcome.output,
        excluded_count=outcome.excluded_count,
        latency_ms=latency_ms,
    )
    return Response(outcome.body, media_type="application/json")


# --- advisor ------------------------------------------------------------------------------


class AdvisorTurn(BaseModel):
    role: str
    text: str


class AdvisorRequest(BaseModel):
    query: str = Field(min_length=1)
    history: list[AdvisorTurn] = []
    debug: bool = False


@app.post("/api/advisor/query")
def advisor_query(
    body: AdvisorRequest, user: Annotated[CurrentUser, Depends(require("0.8.2"))]
) -> Response:
    started = time.perf_counter()
    lang = _lang(body.query)
    if len(body.query) > MAX_QUERY_CHARS:
        return _message_response("M5", lang, 413, max=MAX_QUERY_CHARS)
    if wait := _seconds_until_allowed(user):
        return _message_response("M6", lang, 429, n=wait)
    try:
        with as_user(user.id) as conn:
            outcome = advisor.run(
                conn,
                body.query,
                [t.text for t in body.history if t.role == "user"],
                debug=body.debug,
            )
    except llm.LLMTimeout as exc:
        log.warning("M4: %r caused by %r", exc, exc.__cause__)
        return _message_response("M4", lang, 504)
    except llm.LLMUnavailable as exc:
        log.warning("M3: %r caused by %r", exc, exc.__cause__)
        return _message_response("M3", lang, 503)
    _audit(
        user,
        "advisor.query",
        outcome.message_id or outcome.output,
        grade=outcome.grade,
        output_type=outcome.output,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return Response(outcome.body, media_type="application/json")


# --- documents ----------------------------------------------------------------------------


@app.get("/api/documents/{document_id}/passages/{chunk_id}")
def view_passage(
    document_id: str,
    chunk_id: int,
    user: Annotated[CurrentUser, Depends(require("0.8.1"))],
) -> dict[str, Any]:
    with as_user(user.id) as conn:
        row = conn.execute(
            """
            SELECT c.id, c.text_original, c.page, c.heading, c.sheet, c.cell_range,
                   d.title, d.file_name, d.language
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.id = %s AND d.id = %s
            """,
            (chunk_id, document_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail={"message_id": "M1"})
        neighbours = conn.execute(
            "SELECT id, text_original, page, heading, sheet, cell_range FROM chunks"
            " WHERE document_id = %s ORDER BY ordinal",
            (document_id,),
        ).fetchall()
    return {
        "document_id": document_id,
        "title": row["title"],
        "file_name": row["file_name"],
        "language": row["language"],
        "chunk_id": chunk_id,
        "passages": [dict(n) for n in neighbours],
    }


@app.get("/api/documents/{document_id}/download")
def download(document_id: str, user: Annotated[CurrentUser, Depends(require("0.8.1"))]) -> Response:
    with as_user(user.id) as conn:
        row = conn.execute(
            "SELECT d.file_name, d.mime_type, f.content FROM documents d"
            " JOIN document_files f ON f.document_id = d.id WHERE d.id = %s",
            (document_id,),
        ).fetchone()
    if row is None:
        # Same response whether the document is missing or hidden by policy.
        raise HTTPException(status_code=404, detail={"message_id": "M1"})
    _audit(user, "document.download", "ok", resource_type="document", resource_id=document_id)
    return Response(
        bytes(row["content"]),
        media_type=row["mime_type"],
        headers={"Content-Disposition": f'attachment; filename="{row["file_name"]}"'},
    )


# --- admin --------------------------------------------------------------------------------


@app.get("/api/admin/users")
def admin_users(
    user: Annotated[CurrentUser, Depends(require("0.8.17"))],
) -> list[dict[str, Any]]:
    with as_user(user.id) as conn:
        rows = conn.execute(
            """
            SELECT u.email, u.name, u.role, u.active,
                   coalesce(array_agg(s.event_id) FILTER (WHERE s.event_id IS NOT NULL), '{}') AS events
            FROM users u LEFT JOIN user_scopes s ON s.user_id = u.id
            GROUP BY u.id ORDER BY u.role, u.email
            """
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/messages")
def messages() -> dict[str, dict[str, str]]:
    """The defined messages, so the web client renders M9/M10 without its own copies."""
    ids: list[MessageId] = [
        "M1",
        "M2",
        "M3",
        "M4",
        "M5",
        "M6",
        "M7",
        "M8",
        "M9",
        "M10",
        "M11",
        "M12",
        "PAYMENT",
    ]
    return {i: {"en": message(i, "en"), "ar": message(i, "ar")} for i in ids}


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "llm": "claude" if settings.use_live_llm() else "offline",
            "search": "cohere" if settings.use_live_cohere() else "offline",
        }
    )
