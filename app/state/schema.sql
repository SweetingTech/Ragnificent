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
