-- Columns nothing writes or reads, dropped rather than carried.
--
-- field_results.ocr_value and .agreed backed PRD §5.3's dual-reader agreement
-- gate. OCR is a fallback here, not an always-on second reader, so neither was
-- ever written. .reader_value was written but only ever duplicated .label_value
-- and nothing read it back. records.supersedes_id was for PRD §12's refile
-- link, which this build does not have.
ALTER TABLE field_results DROP COLUMN reader_value;
ALTER TABLE field_results DROP COLUMN ocr_value;
ALTER TABLE field_results DROP COLUMN agreed;
ALTER TABLE records       DROP COLUMN supersedes_id;
