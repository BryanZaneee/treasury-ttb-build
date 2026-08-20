"""Job queue: commit a staged batch and/or verify records (PRD §5.1, §5.5).

Jobs run on a background thread so the reviewer sees per-record progress over
SSE, and one failing record never aborts the rest.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import batching
import csv_io
import db
from routers import batches, records

router = APIRouter(tags=["jobs"])


class JobCreateRequest(BaseModel):
    scope: Literal["pending", "batch", "ids"]
    batch_id: str | None = None
    # scope "ids": verify exactly these records. The reviewer selected them in
    # the inbox, so the set is theirs to choose - the server does not re-derive
    # it from a filter that may have moved on since.
    record_ids: list[str] = []
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
    events: list[dict[str, Any]] = []
    error: str | None = None


# Job progress is a JSON document rather than a process dict: PRD §5 runs two
# workers, and the reviewer polling /jobs/{id} will not reliably reach the one
# running the job. A restart still loses in-flight progress; the records
# themselves are already durable.
def save_job(job: Job) -> Job:
    db.doc_put("job", job.id, job.model_dump_json())
    return job


def load_job(job_id: str) -> Job | None:
    body = db.doc_get("job", job_id)
    return Job.model_validate_json(body) if body is not None else None


def _commit_batch(job: Job, batch_id: str) -> list[str]:
    """File every non-ambiguous staged row. Ambiguous rows block the whole
    commit (PRD §5.5); missing-image rows file and are simply not verifiable."""
    entry = batches.get_staged(batch_id)
    if entry is None:
        raise KeyError(f"unknown batch {batch_id!r}")

    # Block, don't skip: a caller bypassing the UI must not lose rows silently.
    unresolved = batching.unresolved(entry.rows)
    if unresolved:
        raise ValueError(
            "resolve the ambiguous row(s) before committing: "
            + ", ".join(str(n) for n in unresolved)
        )

    record_ids = []
    received = datetime.now(UTC).isoformat()
    for row in entry.rows:
        values = row.values
        record_id = db.next_record_id()
        db.insert_record(
            {
                "id": record_id,
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
                # An exported mirror writes SQLite's 1/0 here, the blank template
                # writes true/false. One truthiness rule for both (csv_io).
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


def _verify_one(job: Job, record_id: str) -> None:
    row = db.get_record(record_id)
    if row is None:
        job.failed += 1
        return
    try:
        record = records.verify_record(record_id)
    except Exception as exc:  # noqa: BLE001 - one bad record must not abort the job
        job.failed += 1
        job.events.append({"event": "error", "record_id": record_id, "detail": str(exc)[:200]})
        return
    verdict = record.result or "unknown"
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
            record_ids = _commit_batch(job, body.batch_id)
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
        save_job(job)
        for record_id in record_ids:
            _verify_one(job, record_id)
            job.completed += 1
            # Persist per record: this is what the reviewer's progress bar and
            # the SSE stream read, and they may be served by another worker.
            save_job(job)
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


@router.get("/jobs/{job_id}/events")
def job_events(job_id: str) -> StreamingResponse:
    if load_job(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")

    def stream() -> Any:
        sent = 0
        while True:
            job = load_job(job_id)
            if job is None:
                return
            while sent < len(job.events):
                event = job.events[sent]
                sent += 1
                yield f"event: {event['event']}\ndata: {json.dumps(event)}\n\n"
            progress = {"completed": job.completed, "total": job.total, "state": job.state}
            yield f"event: progress\ndata: {json.dumps(progress)}\n\n"
            if job.state != "running" and sent >= len(job.events):
                return
            threading.Event().wait(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream")
