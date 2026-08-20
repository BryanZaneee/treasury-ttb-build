-- Extraction cache (PRD §5.2). The key carries every input that can change a
-- reading - image hash, prompt version, provider, model, effort - so a config
-- change produces a new entry rather than serving the previous reader's answer.
-- In SQLite rather than a process dict because §5 deploys two Uvicorn workers.
CREATE TABLE IF NOT EXISTS extraction_cache (
    key          TEXT PRIMARY KEY,
    reading_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
