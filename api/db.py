"""SQLite system of record. Stdlib sqlite3 only - no ORM (PRD §4).

WAL mode permits concurrent readers. Schema is applied from migrations/ at
boot inside a transaction, tracked in schema_version. `records` is the CSV
row: every column maps 1:1 to a CSV column plus eight database-only columns
(PRD §4.1) - so exporting is a SELECT, not a reshape.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import csv_io
from config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

RECORD_COLUMNS = [
    "id", "received", "applicant", "beverage", "filename", "specimen", "quality",
    "app_brand", "app_class_type", "app_alcohol_content", "app_net_contents",
    "app_producer", "app_origin", "app_warning_declared",
    "verified", "result", "elapsed_ms", "engine", "decision", "decided_by",
    "decided_at", "note",
    "override", "supersedes_id", "reader_provider", "reader_model",
    "prompt_version", "prep_ms", "reader_ms", "rules_ms",
]

FIELD_RESULT_COLUMNS = [
    "record_id", "field_key", "app_value", "label_value", "verdict", "note",
    "reader_value", "ocr_value", "agreed", "confidence",
]


def data_dir() -> Path:
    path = Path(settings.data_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "snapshots").mkdir(exist_ok=True)
    (path / "images").mkdir(exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "records.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Apply any migration not yet recorded in schema_version, in order."""
    conn = connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_version")}
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(migration.stem.split("_", 1)[0])
            if version in applied:
                continue
            conn.executescript(migration.read_text())
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            conn.commit()
    finally:
        conn.close()


def snapshot(reason: str) -> Path:
    """File-copy backup before a destructive mutation (import, reset) - PRD §4.4."""
    src = db_path()
    if not src.exists():
        init_db()
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    dest = data_dir() / "snapshots" / f"{stamp}.db"
    conn = connect()
    try:
        backup_conn = sqlite3.connect(dest)
        with backup_conn:
            conn.backup(backup_conn)
        backup_conn.close()
    finally:
        conn.close()
    append_audit(None, "snapshot", {"reason": reason, "path": str(dest)})
    return dest


def append_audit(record_id: str | None, event: str, payload: dict[str, Any]) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO audit (ts, record_id, event, payload_json) VALUES (?, ?, ?, ?)",
            (datetime.now(UTC).isoformat(), record_id, event, json.dumps(payload)),
        )


def insert_record(row: dict[str, Any]) -> None:
    columns = [c for c in RECORD_COLUMNS if c in row]
    placeholders = ", ".join("?" for _ in columns)
    with transaction() as conn:
        conn.execute(
            f"INSERT INTO records ({', '.join(columns)}) VALUES ({placeholders})",
            [row[c] for c in columns],
        )
    append_audit(row["id"], "filed", {k: row[k] for k in columns})
    schedule_mirror_write()


def get_record(record_id: str) -> sqlite3.Row | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        return row  # type: ignore[no-any-return]
    finally:
        conn.close()


def list_records(
    result_filter: str | None = None, query: str | None = None
) -> list[sqlite3.Row]:
    conn = connect()
    try:
        sql = "SELECT * FROM records"
        clauses: list[str] = []
        params: list[str] = []
        if result_filter == "pending":
            clauses.append("verified = 0")
        elif result_filter == "closed":
            clauses.append("decision IS NOT NULL")
        elif result_filter in ("review", "fail"):
            clauses.append("result = ?")
            params.append(result_filter)
        elif result_filter == "attention":
            clauses.append("(result IN ('review', 'fail') AND decision IS NULL)")
        if query:
            clauses.append(
                "(id LIKE ? OR applicant LIKE ? OR app_brand LIKE ? OR filename LIKE ?)"
            )
            like = f"%{query}%"
            params.extend([like, like, like, like])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY received DESC"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def filter_counts() -> dict[str, int]:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN result IN ('review', 'fail') AND decision IS NULL
                         THEN 1 ELSE 0 END) AS attention,
                SUM(CASE WHEN verified = 0 THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN result = 'review' THEN 1 ELSE 0 END) AS review,
                SUM(CASE WHEN result = 'fail' THEN 1 ELSE 0 END) AS fail,
                SUM(CASE WHEN decision IS NOT NULL THEN 1 ELSE 0 END) AS closed
            FROM records
            """
        ).fetchone()
        return {k: row[k] or 0 for k in ("attention", "pending", "review", "fail", "closed")}
    finally:
        conn.close()


def upsert_field_results(record_id: str, results: list[dict[str, Any]]) -> None:
    with transaction() as conn:
        for result in results:
            row = {**result, "record_id": record_id}
            columns = [c for c in FIELD_RESULT_COLUMNS if c in row]
            placeholders = ", ".join("?" for _ in columns)
            updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c not in ("record_id", "field_key"))
            conn.execute(
                f"""
                INSERT INTO field_results ({', '.join(columns)}) VALUES ({placeholders})
                ON CONFLICT (record_id, field_key) DO UPDATE SET {updates}
                """,
                [row[c] for c in columns],
            )
    schedule_mirror_write()


def get_field_results(record_id: str) -> list[sqlite3.Row]:
    conn = connect()
    try:
        return conn.execute(
            "SELECT * FROM field_results WHERE record_id = ? ORDER BY field_key",
            (record_id,),
        ).fetchall()
    finally:
        conn.close()


def wipe() -> None:
    """Delete and recreate the store. Used by reset and by test teardown."""
    global _mirror_timer
    with _mirror_lock:
        if _mirror_timer is not None:
            _mirror_timer.cancel()
            _mirror_timer = None
    conn_path = db_path()
    if conn_path.exists():
        conn_path.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(conn_path) + suffix)
        if extra.exists():
            extra.unlink()
    init_db()


def reset_images_dir() -> None:
    images = data_dir() / "images"
    if images.exists():
        shutil.rmtree(images)
    images.mkdir()


def _pack_field_results(record_id: str) -> tuple[str, str]:
    rows = get_field_results(record_id)
    results = "|".join(f"{r['field_key']}:{r['verdict']}" for r in rows if r["verdict"])
    notes = "|".join(f"{r['field_key']}:{r['note']}" for r in rows if r["note"])
    return results, notes


def mirror_rows() -> list[dict[str, Any]]:
    """Records joined with their packed field_results/field_notes (PRD §4.2)."""
    conn = connect()
    try:
        records = conn.execute("SELECT * FROM records ORDER BY received").fetchall()
    finally:
        conn.close()
    rows = []
    for record in records:
        field_results, field_notes = _pack_field_results(record["id"])
        row = {col: record[col] for col in record.keys()}  # noqa: SIM118 (sqlite3.Row)
        row["field_results"] = field_results
        row["field_notes"] = field_notes
        rows.append(row)
    return rows


def write_mirror() -> None:
    """Regenerate data/records.csv from the database - derived, never read back."""
    data = csv_io.to_csv(mirror_rows())
    (data_dir() / "records.csv").write_bytes(data)


_mirror_lock = threading.Lock()
_mirror_timer: threading.Timer | None = None


def schedule_mirror_write() -> None:
    """Debounced: at most once per second, coalescing a burst of mutations."""
    global _mirror_timer
    with _mirror_lock:
        if _mirror_timer is not None:
            return
        _mirror_timer = threading.Timer(1.0, _flush_mirror)
        _mirror_timer.daemon = True
        _mirror_timer.start()


def _flush_mirror() -> None:
    global _mirror_timer
    write_mirror()
    with _mirror_lock:
        _mirror_timer = None
