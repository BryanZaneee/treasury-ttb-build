"""CSV interchange for the records mirror (PRD §4.2-4.3).

Exactly two functions, both unit-tested independently of the database:
to_csv/from_csv operate on the mirror's column set. Batch-intake CSV (a
different, shorter schema) is batching.py's concern, not this module's.
"""

from __future__ import annotations

import csv
import io
from typing import Any

MIRROR_COLUMNS = [
    "id", "received", "applicant", "beverage", "filename", "specimen", "quality",
    "app_brand", "app_class_type", "app_alcohol_content", "app_net_contents",
    "app_producer", "app_origin", "app_warning_declared",
    "verified", "result", "field_results", "field_notes", "elapsed_ms", "engine",
    "decision", "decided_by", "decided_at", "note",
]

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _sanitize_cell(value: object) -> str:
    """Guard against spreadsheet formula injection on export (PRD §8)."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


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


def from_csv(data: bytes) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig")  # tolerates a BOM
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "app_brand" not in reader.fieldnames:
        raise CsvImportError("app_brand", "missing required column app_brand")

    rows = []
    for raw in reader:
        row = {col: raw.get(col, "") or None for col in MIRROR_COLUMNS}
        row["id"] = raw.get("id") or None  # preserved for idempotent merge-import
        rows.append(row)
    return rows
