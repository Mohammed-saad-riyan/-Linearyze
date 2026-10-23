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

import numpy as np
import yaml

from app.auth.sessions import hash_password
from app.config import REPO_ROOT, settings
from app.db.session import Conn
from app.embeddings import embed_documents
from app.ingest.parsers import parse
from app.text.arabic import normalize
from app.text.terms import passage_context, search_text

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


def _alt_title(doc: dict[str, Any]) -> str | None:
    alt = doc.get("title_en") if doc["language"] == "ar" else doc.get("title_ar")
    return alt if alt and alt != doc["title"] else None


def store_document(conn: Conn, doc: dict[str, Any], uploader: Any) -> list[str]:
    """Write the document row and its file. Returns the texts to embed (empty if the
    document is uploaded but not yet indexed)."""
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
    conn.execute(
        "INSERT INTO document_files (document_id, content) VALUES (%s, %s)", (doc["id"], raw)
    )
    if doc.get("indexed", True) is False:
        return []  # uploaded, waiting for the indexer: indexed_at stays NULL, no chunks
    # Titles (both languages) and the section heading are embedded with each passage, so
    # "the permit application" or "الإيرادات" finds a passage that never repeats them.
    return [passage_context(doc["title"], alt, p.heading, p.text) for p in parse(path)]


def index_document(conn: Conn, doc: dict[str, Any], vectors: list[np.ndarray]) -> None:
    passages = parse(settings.storage_dir / doc["file"])
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
    documents = load_yaml("corpus_manifest.yaml")["documents"]
    texts = {
        d["id"]: store_document(conn, d, uploader["id"] if uploader else None) for d in documents
    }
    # One embedding request for the whole corpus rather than one per document: fewer round
    # trips, and it stays inside the provider's per-minute limits.
    flat = [t for d in documents for t in texts[d["id"]]]
    vectors = iter(embed_documents(flat))
    for doc in documents:
        if texts[doc["id"]]:
            index_document(conn, doc, [next(vectors) for _ in texts[doc["id"]]])
    mark_latest_versions(conn)
    return {d["id"]: len(texts[d["id"]]) for d in documents}
