-- Row-level security (SRS 0.10.1, 1.3.2, 0.9.2.2).
--
-- Every API request runs in a transaction that begins with
--   SELECT set_config('app.user_id', '<uuid>', true)
-- (the transaction-local form of SET LOCAL). The policies read that setting, so full-text
-- search, vector search and metadata lookups are all filtered inside Postgres before any
-- ranking happens. Text a user cannot read never reaches Python, the reranker or the LLM.

CREATE FUNCTION can_read_document(d documents) RETURNS bool
LANGUAGE sql STABLE AS $$
    SELECT coalesce((
        SELECT CASE u.role
            WHEN 'management' THEN true
            WHEN 'employee' THEN d.confidentiality = 'normal'
                AND d.event_id IN (SELECT s.event_id FROM user_scopes s WHERE s.user_id = u.id)
            ELSE false  -- admin: user management only, no document content (SRS 0.7.5)
        END
        FROM users u
        WHERE u.id = nullif(current_setting('app.user_id', true), '')::uuid
          AND u.active
    ), false)
$$;

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY read_documents ON documents FOR SELECT
    USING (can_read_document(documents));

-- The subquery on documents is itself filtered by read_documents, so a chunk is visible
-- exactly when its document is.
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY read_chunks ON chunks FOR SELECT
    USING (EXISTS (SELECT 1 FROM documents d WHERE d.id = chunks.document_id));

-- Audit only (SRS 1.12.2): how many documents matched the query terms but were hidden by
-- policy. Runs as the owner so it can see everything, and returns a bare integer so no
-- title, id or snippet can escape through it.
CREATE FUNCTION excluded_match_count(query_tsquery text) RETURNS int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    WITH matching AS (
        SELECT DISTINCT c.document_id
        FROM chunks c
        WHERE c.tsv @@ to_tsquery('simple', query_tsquery)
    )
    SELECT count(*)::int
    FROM matching m
    JOIN documents d ON d.id = m.document_id
    WHERE NOT can_read_document(d)
$$;
REVOKE ALL ON FUNCTION excluded_match_count(text) FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO ems_app;
GRANT SELECT ON users, user_scopes, events, organizations, org_aliases, documents, chunks
    TO ems_app;
GRANT SELECT, INSERT ON sessions TO ems_app;
GRANT UPDATE (revoked_at) ON sessions TO ems_app;
GRANT INSERT ON audit_log TO ems_app;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO ems_app;
GRANT EXECUTE ON FUNCTION excluded_match_count(text) TO ems_app;
