-- The reading behind the record's current verdict (PRD §5.1: editing the
-- application invalidates the verdict, not the reading).
--
-- The extraction cache cannot answer this: it is keyed on provider, model,
-- effort and prompt version - right for a new verification, wrong here - and it
-- holds nothing for a fallback OCR reading or a store restored from CSV. In each
-- of those a reviewer fixing a typo paid for another read of an unchanged image.
--
-- DB-only, like the other reader_* columns; not a CSV column (PRD §4.2).
ALTER TABLE records ADD COLUMN reading_json TEXT;
