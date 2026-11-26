-- 0001_init: the original job-store schema (jobs table + indexes).
-- Copied verbatim from the former db._SCHEMA. IF NOT EXISTS keeps DBs created
-- before user_version tracking (version 0, table already present) working.

CREATE TABLE IF NOT EXISTS jobs (
    id                 INTEGER PRIMARY KEY,
    platform           TEXT NOT NULL,
    job_key            TEXT NOT NULL,
    url                TEXT,
    title              TEXT NOT NULL DEFAULT '',
    company            TEXT NOT NULL DEFAULT '',
    location           TEXT NOT NULL DEFAULT '',
    description        TEXT,
    description_sha256 TEXT,
    snippet            TEXT,
    salary             TEXT,
    posted_at          TEXT,
    easy_apply         INTEGER,
    remote             INTEGER,
    company_size       TEXT,
    search_name        TEXT,
    status             TEXT NOT NULL DEFAULT 'new',
    decision           TEXT,
    resume_id          TEXT,
    score              INTEGER,
    reason             TEXT,
    decision_json      TEXT,
    error              TEXT,
    first_seen_at      TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    decided_at         TEXT,
    UNIQUE (platform, job_key)
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_desc ON jobs (description_sha256);
