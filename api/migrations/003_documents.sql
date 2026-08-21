-- Short-lived JSON documents: staged batches and job progress. PRD §5 deploys
-- two workers, so a batch staged on one must be committable by the other.
-- Neither is durable state the way `records` is; losing one costs a re-upload.
CREATE TABLE IF NOT EXISTS documents (
    kind       TEXT NOT NULL,
    key        TEXT NOT NULL,
    body       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
