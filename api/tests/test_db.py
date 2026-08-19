"""Round-trip, migration idempotency, and concurrent-write behavior (PRD §4).

conftest.py points DATA_DIR at a throwaway temp directory and wipes the
store before every test.
"""

import sqlite3
import threading
from typing import Any

import db


def _sample_record(record_id: str) -> dict[str, Any]:
    return {
        "id": record_id,
        "received": "2026-08-19T00:00:00+00:00",
        "applicant": "Acme Distilling",
        "beverage": "Distilled Spirits",
        "filename": "old-tom-pass.png",
        "specimen": "old-tom-pass.png",
        "quality": "normal",
        "app_brand": "Old Tom Distillery",
        "app_class_type": "Kentucky Straight Bourbon Whiskey",
        "app_alcohol_content": "45%",
        "app_net_contents": "750 mL",
        "app_producer": "Old Tom Distillery, Bardstown, KY",
        "app_origin": None,
        "app_warning_declared": True,
        "verified": False,
        "result": None,
    }


def test_insert_and_read_round_trip() -> None:
    db.insert_record(_sample_record("rec-1"))
    row = db.get_record("rec-1")
    assert row is not None
    assert row["app_brand"] == "Old Tom Distillery"
    assert row["app_origin"] is None


def test_field_results_round_trip() -> None:
    db.insert_record(_sample_record("rec-2"))
    db.upsert_field_results(
        "rec-2",
        [{"field_key": "brand", "app_value": "Old Tom", "label_value": "Old Tom", "verdict": "match"}],
    )
    results = db.get_field_results("rec-2")
    assert len(results) == 1
    assert results[0]["verdict"] == "match"

    # unique on (record_id, field_key): a second call updates, not duplicates
    db.upsert_field_results(
        "rec-2",
        [{"field_key": "brand", "app_value": "Old Tom", "label_value": "Old Tom", "verdict": "review"}],
    )
    results = db.get_field_results("rec-2")
    assert len(results) == 1
    assert results[0]["verdict"] == "review"


def test_audit_is_append_only() -> None:
    db.insert_record(_sample_record("rec-3"))
    db.append_audit("rec-3", "decision", {"decision": "accepted"})
    db.append_audit("rec-3", "decision", {"decision": "returned"})  # superseded, not overwritten

    conn = sqlite3.connect(db.db_path())
    rows = conn.execute(
        "SELECT event FROM audit WHERE record_id = 'rec-3' ORDER BY seq"
    ).fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["filed", "decision", "decision"]


def test_init_db_is_idempotent() -> None:
    db.init_db()
    db.init_db()  # must not error re-applying an already-recorded migration
    conn = sqlite3.connect(db.db_path())
    versions = conn.execute("SELECT version FROM schema_version").fetchall()
    conn.close()
    assert versions == [(1,)]


def test_concurrent_writes_all_land() -> None:
    errors: list[Exception] = []

    def _insert(n: int) -> None:
        try:
            db.insert_record(_sample_record(f"concurrent-{n}"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_insert, args=(n,)) for n in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    rows = db.list_records()
    assert len({r["id"] for r in rows if r["id"].startswith("concurrent-")}) == 10


def test_snapshot_creates_a_backup_file() -> None:
    db.insert_record(_sample_record("rec-4"))
    path = db.snapshot(reason="test")
    assert path.exists()
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT id FROM records WHERE id = 'rec-4'").fetchone()
    conn.close()
    assert row is not None
