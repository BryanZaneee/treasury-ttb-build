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
    "engine", "decision", "decided_by", "decided_at", "note",
]

# One column beyond PRD §4.2's fixed set, and the reason is worth stating: the
# mirror as specified carries verdicts and notes but not the values they were
# reached from, so a store restored from an export showed every field as "not
# recorded" - a determination with its evidence deleted. JSON in a single cell
# rather than two more `key:value|...` columns because observed label values
# routinely contain both `|` and `:`, which the packed format cannot survive.

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


def to_csv(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(MIRROR_COLUMNS)
    for row in rows:
        writer.writerow(_sanitize_cell(row.get(col)) for col in MIRROR_COLUMNS)
    return buffer.getvalue().encode("utf-8")


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
