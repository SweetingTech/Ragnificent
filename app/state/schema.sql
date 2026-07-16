CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    description TEXT,
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS files (
    file_hash TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    corpus_id TEXT NOT NULL,
    size_bytes INTEGER,
    last_modified DATETIME,
    status TEXT DEFAULT 'PENDING', -- PENDING, PROCESSING, SUCCESS, FAILED, DISABLED
    failure_count INTEGER DEFAULT 0,
    last_error TEXT,
    last_attempt_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    file_hash TEXT NOT NULL,
    corpus_id TEXT NOT NULL,
    chunk_index INTEGER,
    content TEXT,
    metadata_json TEXT, -- page, line, etc
    FOREIGN KEY(file_hash) REFERENCES files(file_hash)
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    job_id TEXT PRIMARY KEY,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT,
    summary_json TEXT
);

-- Immutable provenance receipt for the controlled source-ingestion boundary.
-- The locator is logical (configured root ID + relative path), never a
-- caller-supplied server path.  Agent Harness can map claim evidence to the
-- canonical ragnificent://source-receipts/<receipt_id> reference.
CREATE TABLE IF NOT EXISTS source_receipts (
    receipt_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    corpus_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_record_id TEXT,
    locator_root_id TEXT NOT NULL,
    locator_relative_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    title TEXT,
    privacy TEXT NOT NULL,
    -- Server-computed at receipt creation from the administrator-owned corpus
    -- config. It is immutable so later corpus config changes cannot rewrite
    -- historical Wiki.js publication authority.
    wiki_publication TEXT NOT NULL DEFAULT 'local_only'
        CHECK (wiki_publication IN ('private_wiki_allowed', 'local_only')),
    correlation_id TEXT,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received', -- received, ingested, failed
    indexed_file_hash TEXT,
    ingest_summary_json TEXT,
    received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ingested_at DATETIME,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_source_receipts_corpus_status
ON source_receipts(corpus_id, status);

CREATE INDEX IF NOT EXISTS idx_source_receipts_correlation
ON source_receipts(correlation_id);
