"""Load the demo users, organisations and corpus into Postgres.

Runs on the owner connection. Metadata comes from seed/corpus_manifest.yaml, standing in
for the upload form (SRS 1.2.7); text, page, heading and cell locations come from parsing
the files themselves.
"""

import datetime as dt
import hashlib
import mimetypes
from pathlib import Path
from typing import Any

import yaml

from app.auth.sessions import hash_password
from app.config import REPO_ROOT, settings
from app.db.session import Conn
from app.embeddings import embed_documents
from app.ingest.parsers import parse
from app.text.arabic import normalize
from app.text.terms import search_text

SEED = REPO_ROOT / "seed"
MIME_OVERRIDES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def load_yaml(name: str) -> Any:
    return yaml.safe_load((SEED / name).read_text())


def seed_people(conn: Conn) -> None:
    data = load_yaml("users.yaml")
    for event in data["events"]:
        names = [event["name_en"], event["name_ar"], *event.get("aliases", [])]
        conn.execute(
            "INSERT INTO events (id, name_en, name_ar, aliases) VALUES (%s, %s, %s, %s)",
            (
                event["id"],
                event["name_en"],
                event["name_ar"],
                sorted({normalize(n) for n in names}),
            ),
        )
    for org in data["organizations"]:
        conn.execute(
            "INSERT INTO organizations (id, name_en, name_ar) "
            "VALUES (%(id)s, %(name_en)s, %(name_ar)s)",
            org,
        )
        aliases = {normalize(a) for a in [org["name_en"], org["name_ar"], *org["aliases"]]}
        for alias in sorted(aliases):
            conn.execute(
                "INSERT INTO org_aliases (org_id, alias_normalized) VALUES (%s, %s)",
                (org["id"], alias),
            )
    for user in data["users"]:
        row = conn.execute(
            "INSERT INTO users (email, name, password_hash, role) VALUES (%s, %s, %s, %s) "
            "RETURNING id",
            (user["email"], user["name"], hash_password(user["password"]), user["role"]),
        ).fetchone()
        assert row is not None
        for event_id in user.get("events", []):
            conn.execute(
                "INSERT INTO user_scopes (user_id, event_id) VALUES (%s, %s)",
                (row["id"], event_id),
            )


def passage_context(title: str, title_alt: str | None, heading: str | None, text: str) -> str:
    """What the embedder and the reranker see for a passage. Must match at both ends."""
    return "\n".join(part for part in (title, title_alt, heading, text) if part)


def _alt_title(doc: dict[str, Any]) -> str | None:
    alt = doc.get("title_en") if doc["language"] == "ar" else doc.get("title_ar")
    return alt if alt and alt != doc["title"] else None


def ingest_document(conn: Conn, doc: dict[str, Any], uploader: Any) -> int:
    path: Path = settings.storage_dir / doc["file"]
    raw = path.read_bytes()
    alt = _alt_title(doc)
    conn.execute(
        """
        INSERT INTO documents (
            id, title, title_alt, title_terms, file_name, doc_type, language, series, version,
            sender_org_id, recipient_org_id, direction, reference_no, document_date,
            received_date, submitted_date, event_id, client_org_id, contract_no,
            confidentiality, uploader_id, sha256, storage_path, mime_type)
        VALUES (%(id)s, %(title)s, %(alt)s, %(title_terms)s, %(file_name)s, %(doc_type)s,
            %(language)s, %(series)s, %(version)s, %(sender)s, %(recipient)s, %(direction)s,
            %(reference_no)s, %(document_date)s, %(received_date)s, %(submitted_date)s,
            %(event)s, %(client)s, %(contract_no)s, %(confidentiality)s, %(uploader)s,
            %(sha256)s, %(storage_path)s, %(mime_type)s)
        """,
        {
            **{
                k: doc.get(k)
                for k in (
                    "id",
                    "title",
                    "doc_type",
                    "language",
                    "sender",
                    "recipient",
                    "direction",
                    "reference_no",
                    "document_date",
                    "received_date",
                    "submitted_date",
                    "event",
                    "client",
                    "contract_no",
                    "confidentiality",
                )
            },
            "alt": alt,
            "title_terms": search_text(f"{doc['title']} {alt or ''}"),
            "file_name": path.name,
            "series": doc.get("series", doc["id"]),
            "version": doc.get("version", 1),
            "uploader": uploader,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "storage_path": doc["file"],
            "mime_type": MIME_OVERRIDES.get(path.suffix) or mimetypes.guess_type(path.name)[0],
        },
    )
    if doc.get("indexed", True) is False:
        return 0  # uploaded, waiting for the indexer: indexed_at stays NULL, no chunks

    passages = parse(path)
    # Titles (both languages) and the section heading are embedded with each passage, so
    # "the permit application" or "الإيرادات" finds a passage that never repeats them.
    vectors = embed_documents(
        [passage_context(doc["title"], alt, p.heading, p.text) for p in passages]
    )
    for ordinal, (passage, vector) in enumerate(zip(passages, vectors, strict=True)):
        conn.execute(
            """
            INSERT INTO chunks (document_id, ordinal, text_original, text_normalized,
                                search_terms, embedding, page, heading, sheet, cell_range)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                doc["id"],
                ordinal,
                passage.text,
                normalize(passage.text),
                search_text(f"{passage.heading or ''} {passage.text}"),
                vector,
                passage.page,
                passage.heading,
                passage.sheet,
                passage.cell_range,
            ),
        )
    conn.execute(
        "UPDATE documents SET indexed_at = %s WHERE id = %s", (dt.datetime.now(dt.UTC), doc["id"])
    )
    return len(passages)


def mark_latest_versions(conn: Conn) -> None:
    conn.execute(
        """
        UPDATE documents d SET is_latest = (d.version = (
            SELECT max(v.version) FROM documents v WHERE v.series = d.series))
        """
    )


def ingest_corpus(conn: Conn) -> dict[str, int]:
    uploader = conn.execute(
        "SELECT id FROM users WHERE role = 'management' ORDER BY email LIMIT 1"
    ).fetchone()
    counts = {}
    for doc in load_yaml("corpus_manifest.yaml")["documents"]:
        counts[doc["id"]] = ingest_document(conn, doc, uploader["id"] if uploader else None)
    mark_latest_versions(conn)
    return counts
