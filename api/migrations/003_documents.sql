-- Short-lived JSON documents: staged batches and job progress.
--
-- These were process-local dicts, but PRD §5 deploys two Uvicorn workers, so a
-- reviewer polling a job could hit the worker that never ran it and a batch
-- staged on one worker could not be committed by the other. Neither is durable
-- state in the sense `records` is - losing one costs a re-upload - but both
-- have to be visible to every worker.
CREATE TABLE IF NOT EXISTS documents (
    kind       TEXT NOT NULL,
    key        TEXT NOT NULL,
    body       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
