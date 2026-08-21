-- Extraction cache (PRD §5.2). Keyed on every input that can change a reading,
-- so a config change cannot serve the previous reader's answer. In SQLite rather
-- than a process dict because §5 deploys two workers.
CREATE TABLE IF NOT EXISTS extraction_cache (
    key          TEXT PRIMARY KEY,
    reading_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
