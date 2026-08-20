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
from adjudicate import FIELD_KEYS as FIELD_ORDER
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


@contextmanager
def exclusive() -> Iterator[sqlite3.Connection]:
    """A transaction that takes the write lock *before* it reads.

    `transaction()` begins deferred, so sqlite3 opens the transaction on the
    first write - a read-modify-write through it can interleave with another
    worker's and both can act on the same snapshot. BEGIN IMMEDIATE serialises
    the whole sequence, which is what claiming staged batch rows needs: PRD §9
    runs more than one worker, and filing the same row twice writes two records.
    """
    conn = connect()
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
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
    prune_snapshots()
    return dest


# PRD §8 keeps backups for 30 days. Snapshots are taken before every import and
# reset, so without this the directory grows for the life of the deployment.
SNAPSHOT_RETENTION_DAYS = 30


def prune_snapshots(keep_days: int = SNAPSHOT_RETENTION_DAYS) -> list[Path]:
    """Delete snapshots older than the retention window. Returns what went.

    Never deletes the newest one whatever its age: a store that has sat
    untouched for a month should still have something to restore from.
    """
    snapshots = sorted((data_dir() / "snapshots").glob("*.db"))
    if not snapshots:
        return []
    cutoff = datetime.now(UTC).timestamp() - keep_days * 86400
    removed = []
    for path in snapshots[:-1]:
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed.append(path)
    return removed


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


def update_record(record_id: str, **columns: Any) -> None:
    """Patch named columns on one record. Unknown column names are rejected
    rather than silently dropped - a typo here would lose a verdict."""
    unknown = set(columns) - set(RECORD_COLUMNS)
    if unknown:
        raise ValueError(f"unknown record columns: {sorted(unknown)}")
    if not columns:
        return
    assignments = ", ".join(f"{c} = ?" for c in columns)
    with transaction() as conn:
        conn.execute(
            f"UPDATE records SET {assignments} WHERE id = ?",
            [*columns.values(), record_id],
        )
    schedule_mirror_write()


def clear_field_results(record_id: str) -> None:
    """Editing an application invalidates its prior verdict (PRD §5.1)."""
    with transaction() as conn:
        conn.execute("DELETE FROM field_results WHERE record_id = ?", (record_id,))
    schedule_mirror_write()


def upsert_records(rows: list[dict[str, Any]]) -> None:
    """Insert or update many records in ONE transaction, so an import either
    lands whole or not at all."""
    if not rows:
        return
    with transaction() as conn:
        for row in rows:
            columns = [c for c in RECORD_COLUMNS if c in row]
            placeholders = ", ".join("?" for _ in columns)
            updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c != "id")
            conn.execute(
                f"""
                INSERT INTO records ({", ".join(columns)}) VALUES ({placeholders})
                ON CONFLICT (id) DO UPDATE SET {updates}
                """,
                [row[c] for c in columns],
            )
    schedule_mirror_write()


def get_record(record_id: str) -> sqlite3.Row | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        return row  # type: ignore[no-any-return]
    finally:
        conn.close()


def list_records(result_filter: str | None = None) -> list[sqlite3.Row]:
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
            clauses.append("(result IN ('review', 'fail', 'invalid') AND decision IS NULL)")
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
                SUM(CASE WHEN result IN ('review', 'fail', 'invalid') AND decision IS NULL
                         THEN 1 ELSE 0 END) AS attention,
                SUM(CASE WHEN verified = 0 THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN result = 'review' THEN 1 ELSE 0 END) AS review,
                SUM(CASE WHEN result = 'fail' THEN 1 ELSE 0 END) AS fail,
                SUM(CASE WHEN decision IS NOT NULL THEN 1 ELSE 0 END) AS closed,
                COUNT(*) AS total
            FROM records
            """
        ).fetchone()
        return {
            k: row[k] or 0
            for k in ("attention", "pending", "review", "fail", "closed", "total")
        }
    finally:
        conn.close()


def upsert_field_results(record_id: str, results: list[dict[str, Any]]) -> None:
    upsert_field_results_many([{**r, "record_id": record_id} for r in results])


def upsert_field_results_many(rows: list[dict[str, Any]]) -> None:
    """Field results for one or many records, in a single transaction."""
    if not rows:
        return
    with transaction() as conn:
        for row in rows:
            columns = [c for c in FIELD_RESULT_COLUMNS if c in row]
            placeholders = ", ".join("?" for _ in columns)
            updates = ", ".join(
                f"{c}=excluded.{c}" for c in columns if c not in ("record_id", "field_key")
            )
            conn.execute(
                f"""
                INSERT INTO field_results ({", ".join(columns)}) VALUES ({placeholders})
                ON CONFLICT (record_id, field_key) DO UPDATE SET {updates}
                """,
                [row[c] for c in columns],
            )
    schedule_mirror_write()


def get_field_results(record_id: str) -> list[sqlite3.Row]:
    """Ordered as PRD §3.1 lists the fields, not alphabetically - the
    determination view reads top to bottom the way the table is written."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM field_results WHERE record_id = ?", (record_id,)
        ).fetchall()
    finally:
        conn.close()
    order = {key: i for i, key in enumerate(FIELD_ORDER)}
    return sorted(rows, key=lambda r: order.get(r["field_key"], len(order)))


def next_record_id() -> str:
    """COLA-YYYY-NNNN, continuing the highest number already in the store.

    The suffix is read with one aggregate rather than by scanning every id into
    Python: filing a 300-row batch called this once per row, which made the
    commit quadratic in the size of the store.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT MAX(CAST(substr(id, 11) AS INTEGER)) AS n FROM records "
            "WHERE id LIKE 'COLA-____-%' ESCAPE '\\'"
        ).fetchone()
    finally:
        conn.close()
    highest = max(4099, int(row["n"] or 0))
    return f"COLA-{datetime.now(UTC).year}-{highest + 1}"


def insert_new_record(row: dict[str, Any]) -> str:
    """Allocate an id and file the row under it, returning the id.

    Allocation and insert are two statements, so two concurrent filings can pick
    the same number - and PRD §9 runs more than one worker. The unique index on
    `records.id` is what actually decides, and losing that race is a retry, not
    the 500 an uncaught IntegrityError produced.
    """
    for _ in range(8):
        row["id"] = next_record_id()
        try:
            insert_record(row)
        except sqlite3.IntegrityError:
            continue
        return str(row["id"])
    raise RuntimeError("could not allocate a record id")


_background: list[threading.Thread] = []


def run_in_background(fn: Any, *args: Any) -> None:
    """Fire-and-forget work that writes to the store.

    Tracked so wipe() can wait for it: an unjoined writer lands in the next
    test's database, the same way a pending mirror timer would.
    """
    thread = threading.Thread(target=fn, args=args, daemon=True)
    _background.append(thread)
    thread.start()


def doc_put(kind: str, key: str, body: str) -> None:
    """Store one JSON document, visible to every worker.

    ponytail: the whole document is rewritten on each update, so a job's event
    list is re-serialised once per record. Fine at PRD §8's 300-record batch;
    append events to their own table if a batch ever gets much larger.
    """
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO documents (kind, key, body, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT (kind, key) DO UPDATE SET
                body = excluded.body, updated_at = excluded.updated_at
            """,
            (kind, key, body, datetime.now(UTC).isoformat()),
        )


def doc_get(kind: str, key: str) -> str | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT body FROM documents WHERE kind = ? AND key = ?", (kind, key)
        ).fetchone()
        return str(row["body"]) if row is not None else None
    finally:
        conn.close()


def extraction_cache_get(key: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT reading_json FROM extraction_cache WHERE key = ?", (key,)
        ).fetchone()
        return json.loads(row["reading_json"]) if row is not None else None
    finally:
        conn.close()


def extraction_cache_put(key: str, payload: dict[str, Any]) -> None:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO extraction_cache (key, reading_json, created_at) VALUES (?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET
                reading_json = excluded.reading_json, created_at = excluded.created_at
            """,
            (key, json.dumps(payload), datetime.now(UTC).isoformat()),
        )


def wipe() -> None:
    """Delete and recreate the store. Used by reset and by test teardown."""
    global _mirror_timer
    for thread in _background:
        thread.join(timeout=5)
    _background.clear()
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


def mirror_rows() -> list[dict[str, Any]]:
    """Every record with its field results packed into the mirror's cells.

    Both tables are read once. Packing per record through `get_field_results`
    meant a fresh connection and a query per row, so regenerating the mirror for
    a 300-record store opened 301 connections - on the debounce timer once a
    second through a batch commit, and on the request path for both exports.
    """
    conn = connect()
    try:
        records = conn.execute("SELECT * FROM records ORDER BY received").fetchall()
        results = conn.execute("SELECT * FROM field_results").fetchall()
    finally:
        conn.close()

    order = {key: i for i, key in enumerate(FIELD_ORDER)}
    by_record: dict[str, list[sqlite3.Row]] = {}
    for result in results:
        by_record.setdefault(result["record_id"], []).append(result)
    for grouped in by_record.values():
        grouped.sort(key=lambda r: order.get(r["field_key"], len(order)))

    rows = []
    for record in records:
        fields = by_record.get(record["id"], [])
        row = {col: record[col] for col in record.keys()}  # noqa: SIM118 (sqlite3.Row)
        row["field_results"] = "|".join(
            f"{r['field_key']}:{r['verdict']}" for r in fields if r["verdict"]
        )
        row["field_notes"] = "|".join(
            f"{r['field_key']}:{r['note']}" for r in fields if r["note"]
        )
        row["field_values"] = csv_io.pack_field_values(fields)
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
