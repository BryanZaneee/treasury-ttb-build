-- The two columns the inbox sorts and filters on that 001 left unindexed.
-- `received` orders every list and every mirror rebuild, so both were doing a
-- filesort; `decision` drives the "closed" filter every view asks for.
CREATE INDEX IF NOT EXISTS idx_records_received ON records (received);
CREATE INDEX IF NOT EXISTS idx_records_decision ON records (decision);
