"""Job queue: commit a staged batch and/or verify records (PRD §5.1, §5.5).

Jobs run on a background thread and persist progress per record, so the
reviewer can poll it; one failing record never aborts the rest.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import csv_io
import db
from config import settings
from routers import batches, records

router = APIRouter(tags=["jobs"])


class JobCreateRequest(BaseModel):
    scope: Literal["pending", "batch", "ids"]
    batch_id: str | None = None
    # scope "ids": exactly these records. The reviewer chose them, so the server
    # does not re-derive the set from a filter that may have moved on.
    record_ids: list[str] = []
    # scope "batch": file only these staged rows; the rest stay staged.
    rows: list[int] = []
    verify_now: bool = True


class Job(BaseModel):
    id: str
    scope: str
    state: Literal["running", "done", "error"] = "running"
    total: int = 0
    completed: int = 0
    committed: int = 0
    failed: int = 0
    verdicts: dict[str, int] = {}
    # A `pending` job derives its own set server side, so without this the
    # browser knows how many rows it covers but not which.
    record_ids: list[str] = []
    events: list[dict[str, Any]] = []
    error: str | None = None


# A document, not a process dict: PRD §5 runs two workers and the reviewer
# polling /jobs/{id} may not reach the one running it. The records are durable.
def save_job(job: Job) -> Job:
    db.doc_put("job", job.id, job.model_dump_json())
    return job


def load_job(job_id: str) -> Job | None:
    body = db.doc_get("job", job_id)
    return Job.model_validate_json(body) if body is not None else None


def _commit_batch(job: Job, batch_id: str, only: list[int] | None = None) -> list[str]:
    """File the staged rows. Ambiguous rows block the commit (PRD §5.5);
    missing-image rows file and are simply not verifiable. `only` files a
    subset, which is then removed from the staged document."""
    # Claimed inside the transaction that reads them, so a second commit finds
    # nothing rather than filing everything twice.
    chosen, blocking = batches.claim_rows(batch_id, only)
    # Block, don't skip: a caller bypassing the UI must not lose rows silently.
    if blocking:
        raise ValueError(
            "resolve the ambiguous row(s) before committing: "
            + ", ".join(str(n) for n in blocking)
        )
    if not chosen:
        raise ValueError("no staged rows to file")

    record_ids = []
    received = datetime.now(UTC).isoformat()
    for row in chosen:
        values = row.values
        record_id = db.insert_new_record(
            {
                "received": received,
                "applicant": values.get("applicant", ""),
                "beverage": values.get("class_type", ""),
                "filename": row.filename,
                "specimen": row.image or "",
                "quality": None,
                "app_brand": values.get("brand_name", ""),
                "app_class_type": values.get("class_type", ""),
                "app_alcohol_content": values.get("alcohol_content", ""),
                "app_net_contents": values.get("net_contents", ""),
                "app_producer": values.get("producer") or None,
                "app_origin": values.get("country_of_origin") or None,
                # 1/0 from an export, true/false from the template (csv_io).
                "app_warning_declared": csv_io.parse_bool(values.get("government_warning")),
                "verified": False,
                "result": None,
            }
        )
        job.committed += 1
        # A row with no image files, but there is nothing to verify against.
        if row.image:
            record_ids.append(record_id)

    return record_ids


def _verify_one(job: Job, record_id: str, lock: threading.Lock) -> None:
    """Verify one record on a pool thread; counters are mutated under the lock."""
    row = db.get_record(record_id)
    if row is None:
        with lock:
            job.failed += 1
        return
    try:
        record = records.verify_record(record_id)
    except Exception as exc:  # noqa: BLE001 - one bad record must not abort the job
        with lock:
            job.failed += 1
            job.events.append(
                {"event": "error", "record_id": record_id, "detail": str(exc)[:200]}
            )
        return
    verdict = record.result or "unknown"
    with lock:
        job.verdicts[verdict] = job.verdicts.get(verdict, 0) + 1
        job.events.append(
            {
                "event": "record",
                "record_id": record_id,
                "filename": record.filename,
                "result": verdict,
                "elapsed_ms": record.elapsed_ms,
            }
        )


def _run(job: Job, body: JobCreateRequest) -> None:
    try:
        record_ids: list[str] = []
        if body.scope == "batch":
            if not body.batch_id:
                raise ValueError("batch_id is required for scope 'batch'")
            record_ids = _commit_batch(job, body.batch_id, body.rows or None)
        elif body.scope == "ids":
            if not body.record_ids:
                raise ValueError("record_ids is required for scope 'ids'")
            record_ids = list(body.record_ids)
        else:
            record_ids = [
                r["id"] for r in db.list_records(result_filter="pending") if r["specimen"]
            ]

        if not body.verify_now:
            job.total = job.committed
            job.completed = job.committed
            job.state = "done"
            return

        job.total = len(record_ids)
        job.record_ids = record_ids
        save_job(job)
        # PRD §8: bounded - 300 one at a time misses the budget, 300 at once
        # breaches the provider. Readers are sync, so a pool beats going async.
        lock = threading.Lock()

        def verify_and_record(record_id: str) -> None:
            _verify_one(job, record_id, lock)
            with lock:
                job.completed += 1
                # Per record: the progress bar may be served by another worker.
                save_job(job)

        workers = max(1, settings.reader_concurrency)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(verify_and_record, record_ids))
        job.state = "done"
    except Exception as exc:  # noqa: BLE001
        job.state = "error"
        job.error = str(exc)[:300]
    finally:
        job.events.append({"event": "done", "state": job.state})
        save_job(job)


@router.post("/jobs", response_model=Job)
def create_job(body: JobCreateRequest) -> Job:
    job = save_job(Job(id=f"job-{uuid.uuid4().hex[:8]}", scope=body.scope))
    db.run_in_background(_run, job, body)
    return job


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str) -> Job:
    job = load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job
