"""CSV interchange for the records mirror (PRD §4.2-4.3).

Exactly two functions, both unit-tested independently of the database:
to_csv/from_csv operate on the mirror's column set. Batch-intake CSV (a
different, shorter schema) is batching.py's concern, not this module's.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

MIRROR_COLUMNS = [
    "id", "received", "applicant", "beverage", "filename", "specimen", "quality",
    "app_brand", "app_class_type", "app_alcohol_content", "app_net_contents",
    "app_producer", "app_origin", "app_warning_declared",
    "verified", "result", "field_results", "field_notes", "field_values", "elapsed_ms",
    "engine", "decision", "override", "decided_by", "decided_at", "note",
]

# One column beyond PRD §4.2's fixed set, and the reason is worth stating: the
# mirror as specified carries verdicts and notes but not the values they were
# reached from, so a store restored from an export showed every field as "not
# recorded" - a determination with its evidence deleted. JSON in a single cell
# rather than two more `key:value|...` columns because observed label values
# routinely contain both `|` and `:`, which the packed format cannot survive.

# `override` is the second column beyond PRD §4.2's set, and it has to be here:
# accepting a record that did not pass is the one determination a reviewer makes
# against the engine, and an export that drops the flag destroys the only
# evidence that the waiver was deliberate - which is what S8 exists to produce.

# What a reviewer downloads. The mirror above is a restore artifact and reads
# like one; this is the same store without the machine-facing half - no packed
# JSON, no timings, no engine string. The application columns deliberately use
# the batch-intake header names (batching.INTAKE_COLUMNS) so a downloaded export
# can be re-uploaded on Check a batch without being translated first.
REVIEW_COLUMNS = [
    "id", "received", "applicant", "filename",
    "brand_name", "class_type", "alcohol_content", "net_contents",
    "producer", "country_of_origin", "government_warning",
    "result", "issues", "decision", "override", "decided_by", "decided_at", "reason",
]

_REVIEW_SOURCE = {
    "brand_name": "app_brand",
    "class_type": "app_class_type",
    "alcohol_content": "app_alcohol_content",
    "net_contents": "app_net_contents",
    "producer": "app_producer",
    "country_of_origin": "app_origin",
    "government_warning": "app_warning_declared",
    "reason": "note",
}

# The reviewer-facing name for each verified field, so `issues` reads as words
# rather than as the keys the engine compares on.
FIELD_LABEL = {
    "brand": "Brand name",
    "classType": "Class / type",
    "abv": "Alcohol content",
    "net": "Net contents",
    "producer": "Bottler / producer",
    "origin": "Country of origin",
    "warning": "Government warning",
}

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _sanitize_cell(value: object) -> str:
    """Guard against spreadsheet formula injection on export (PRD §8)."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def pack_field_values(rows: list[Any]) -> str:
    """The observed values, as `{field_key: {"app": ..., "label": ...}}`."""
    packed = {
        row["field_key"]: {"app": row["app_value"], "label": row["label_value"]}
        for row in rows
        if row["app_value"] is not None or row["label_value"] is not None
    }
    return json.dumps(packed, ensure_ascii=False, sort_keys=True) if packed else ""


def unpack_field_values(packed: str) -> dict[str, dict[str, str | None]]:
    """Inverse of `pack_field_values`. A cell that will not parse is dropped
    rather than failing the import: the verdicts still restore without it."""
    if not packed.strip():
        return {}
    try:
        loaded = json.loads(packed)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write(columns: list[str], rows: list[dict[str, Any]], cell: Any) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(_sanitize_cell(cell(row, col)) for col in columns)
    return buffer.getvalue().encode("utf-8")


def to_csv(rows: list[dict[str, Any]]) -> bytes:
    return _write(MIRROR_COLUMNS, rows, lambda row, col: row.get(col))


def issues(packed_field_results: str) -> str:
    """The fields that did not match, named in full. Empty when every field
    agreed, which is the common case and should read as blank, not as "none"."""
    out = []
    for chunk in (packed_field_results or "").split("|"):
        key, sep, verdict = chunk.partition(":")
        key, verdict = key.strip(), verdict.strip()
        if sep and key and verdict and verdict != "match":
            out.append(FIELD_LABEL.get(key, key))
    return ", ".join(out)


def to_review_csv(rows: list[dict[str, Any]]) -> bytes:
    def cell(row: dict[str, Any], col: str) -> Any:
        if col == "issues":
            return issues(row.get("field_results", ""))
        return row.get(_REVIEW_SOURCE.get(col, col))

    return _write(REVIEW_COLUMNS, rows, cell)


class CsvImportError(Exception):
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


_TRUE = {"1", "true", "yes", "y", "t"}


def parse_bool(value: object) -> bool:
    """A CSV boolean, however it was written: the exporter emits SQLite's 1/0, a
    hand-authored file true/false, and str(True) writes True."""
    return str(value or "").strip().casefold() in _TRUE


def unpack_field_results(
    record_id: str, packed: str, notes: str, values: str = ""
) -> list[dict[str, Any]]:
    """Rebuild field_results rows from the mirror's packed cells (PRD §4.2).

    Verdict, note and the two observed values restore. `reader_value`,
    `ocr_value`, `agreed` and `confidence` are not in the CSV and do not come
    back - they are per-reader evidence, not the determination.
    """
    note_by_key = {}
    for chunk in (notes or "").split("|"):
        key, sep, text = chunk.partition(":")
        if sep and key.strip():
            note_by_key[key.strip()] = text.strip()

    value_by_key = unpack_field_values(values or "")

    rows: list[dict[str, Any]] = []
    for chunk in (packed or "").split("|"):
        key, sep, verdict = chunk.partition(":")
        key, verdict = key.strip(), verdict.strip()
        if not sep or not key or not verdict:
            continue
        observed = value_by_key.get(key) or {}
        rows.append(
            {
                "record_id": record_id,
                "field_key": key,
                "verdict": verdict,
                "note": note_by_key.get(key),
                "app_value": observed.get("app"),
                "label_value": observed.get("label"),
            }
        )
    return rows


def from_csv(data: bytes) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "app_brand" not in reader.fieldnames:
        # The other CSV this service hands out is the batch-intake template
        # (batching.INTAKE_COLUMNS), which files new applications rather than
        # restoring determinations. Say so instead of naming a column the
        # operator never saw.
        if reader.fieldnames and "brand_name" in reader.fieldnames:
            raise CsvImportError(
                "app_brand",
                "this is a batch-intake CSV, not a records export - "
                "file it on Check a batch, which pairs it with label images",
            )
        raise CsvImportError("app_brand", "missing required column app_brand")

    rows = []
    for raw in reader:
        row = {col: raw.get(col, "") or None for col in MIRROR_COLUMNS}
        row["id"] = raw.get("id") or None  # preserved for idempotent merge-import
        rows.append(row)
    return rows
