-- records is the CSV row: columns 1-22 are the CSV columns verbatim (PRD §4.1),
-- plus eight database-only columns that never appear in the CSV mirror.
CREATE TABLE records (
    id                   TEXT PRIMARY KEY,
    received             TEXT NOT NULL,
    applicant            TEXT NOT NULL,
    beverage             TEXT NOT NULL,
    filename             TEXT NOT NULL,
    specimen             TEXT NOT NULL,
    quality              TEXT,
    app_brand            TEXT NOT NULL,
    app_class_type       TEXT NOT NULL,
    app_alcohol_content  TEXT NOT NULL,
    app_net_contents     TEXT NOT NULL,
    app_producer         TEXT,
    app_origin           TEXT,
    app_warning_declared INTEGER NOT NULL DEFAULT 0,
    verified             INTEGER NOT NULL DEFAULT 0,
    result               TEXT,
    elapsed_ms           INTEGER,
    engine               TEXT,
    decision             TEXT,
    decided_by           TEXT,
    decided_at           TEXT,
    note                 TEXT,

    -- database-only, not exported to the CSV mirror
    override             INTEGER NOT NULL DEFAULT 0,
    supersedes_id        TEXT,
    reader_provider       TEXT,
    reader_model          TEXT,
    prompt_version        TEXT,
    prep_ms               INTEGER,
    reader_ms             INTEGER,
    rules_ms              INTEGER
);

-- one row per verified field per record (PRD §4.1) - replaces v1.0's packed cell
CREATE TABLE field_results (
    record_id     TEXT NOT NULL REFERENCES records(id),
    field_key     TEXT NOT NULL,
    app_value     TEXT,
    label_value   TEXT,
    verdict       TEXT,
    note          TEXT,
    reader_value  TEXT,
    ocr_value     TEXT,
    agreed        INTEGER,
    confidence    REAL,
    PRIMARY KEY (record_id, field_key)
);

-- append-only event log (PRD §4.1) - superseded verdicts are retained here,
-- never overwritten; records holds only the current state.
CREATE TABLE audit (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    record_id    TEXT,
    event        TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX idx_records_result ON records(result);
CREATE INDEX idx_records_verified ON records(verified);
CREATE INDEX idx_audit_record_id ON audit(record_id);
