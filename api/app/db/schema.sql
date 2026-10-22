-- Owned by ems_owner. The API connects as ems_app, which has no BYPASSRLS and owns nothing,
-- so every policy below applies to it.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email        text NOT NULL UNIQUE,
    name         text NOT NULL,
    password_hash text NOT NULL,
    role         text NOT NULL CHECK (role IN ('management', 'employee', 'admin')),
    perm_version int  NOT NULL DEFAULT 1,
    active       bool NOT NULL DEFAULT true
);

CREATE TABLE events (
    id      text PRIMARY KEY,
    name_en text NOT NULL,
    name_ar text NOT NULL
);

-- Employee scope = assigned events (SRS 0.9.2.2).
CREATE TABLE user_scopes (
    user_id  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_id text NOT NULL REFERENCES events(id),
    PRIMARY KEY (user_id, event_id)
);

CREATE TABLE sessions (
    token_hash text PRIMARY KEY,
    user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz
);

CREATE TABLE organizations (
    id      text PRIMARY KEY,
    name_en text NOT NULL,
    name_ar text NOT NULL
);

-- Aliases are stored normalized (app/text/arabic.py), so "Ministry A", "وزارة أ" and
-- "MoCA" all resolve with one equality lookup.
CREATE TABLE org_aliases (
    org_id           text NOT NULL REFERENCES organizations(id),
    alias_normalized text NOT NULL,
    PRIMARY KEY (org_id, alias_normalized)
);
CREATE INDEX org_aliases_alias ON org_aliases (alias_normalized);

CREATE TABLE documents (
    id                text PRIMARY KEY,
    title             text NOT NULL,
    title_alt         text,               -- the title in the other language, if the document has one
    title_terms       text NOT NULL,      -- app/text/terms.py search_text() of both titles
    title_tsv         tsvector GENERATED ALWAYS AS (to_tsvector('simple', title_terms)) STORED,
    file_name         text NOT NULL,
    doc_type          text NOT NULL,
    language          text NOT NULL CHECK (language IN ('en', 'ar')),
    series            text NOT NULL,      -- versions of one document share a series
    version           int  NOT NULL DEFAULT 1,
    is_latest         bool NOT NULL DEFAULT true,
    sender_org_id     text REFERENCES organizations(id),
    recipient_org_id  text REFERENCES organizations(id),
    direction         text CHECK (direction IN ('incoming', 'outgoing', 'internal')),
    reference_no      text,
    document_date     date,
    received_date     date,
    submitted_date    date,
    event_id          text REFERENCES events(id),
    client_org_id     text REFERENCES organizations(id),
    contract_no       text,
    confidentiality   text NOT NULL DEFAULT 'normal' CHECK (confidentiality IN ('normal', 'confidential')),
    uploader_id       uuid REFERENCES users(id),
    uploaded_at       timestamptz NOT NULL DEFAULT now(),
    indexed_at        timestamptz,        -- NULL until chunks and vectors are written
    sha256            text NOT NULL,
    storage_path      text NOT NULL,
    mime_type         text NOT NULL
);
CREATE INDEX documents_sender ON documents (sender_org_id, direction, received_date);
CREATE INDEX documents_series ON documents (series, version);
CREATE INDEX documents_title_tsv ON documents USING gin (title_tsv);

CREATE TABLE chunks (
    id              bigserial PRIMARY KEY,
    document_id     text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal         int  NOT NULL,
    text_original   text NOT NULL,
    text_normalized text NOT NULL,      -- arabic.normalize(text_original); quotes are matched here
    search_terms    text NOT NULL,      -- terms.search_text(): stemmed, stopwords removed
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('simple', search_terms)) STORED,
    embedding       vector(1024) NOT NULL,
    page            int,
    heading         text,
    sheet           text,
    cell_range      text
);
CREATE INDEX chunks_tsv ON chunks USING gin (tsv);
CREATE INDEX chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_document ON chunks (document_id, ordinal);

-- SRS 1.12: what happened, never what was asked or answered.
CREATE TABLE audit_log (
    id             bigserial PRIMARY KEY,
    ts             timestamptz NOT NULL DEFAULT now(),
    user_id        uuid,
    role           text,
    action         text NOT NULL,
    resource_type  text,
    resource_id    text,
    result         text NOT NULL,
    grade          text,
    output_type    text,
    excluded_count int,
    latency_ms     int
);
