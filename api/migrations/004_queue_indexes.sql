-- The two columns the inbox actually sorts and filters on that 001 left
-- unindexed.
--
-- `received` orders every db.list_records call and every mirror regeneration,
-- so both were doing a filesort over the whole table. `decision` drives the
-- "closed" filter and the closed aggregate in filter_counts, which every view
-- asks for. Cheap at PRD §8's 300 records; the point is that the queue stays
-- flat as the store grows past the fixture set.
CREATE INDEX IF NOT EXISTS idx_records_received ON records (received);
CREATE INDEX IF NOT EXISTS idx_records_decision ON records (decision);
