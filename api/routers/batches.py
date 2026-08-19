"""Batch staging endpoint (PRD §5.1, §5.5).

Staging writes nothing. It parses the CSV, pairs images by filename, and returns
a preview with per-row buckets and errors. The staged batch is held until a job
commits it (`POST /api/jobs`).
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

import batching
import db
import seed
import uploads
from batching import BatchCsvError

router = APIRouter(tags=["batches"])

PairingBucket = Literal["matched", "matched_fuzzy", "missing_image", "ambiguous"]


class StagedRow(BaseModel):
    row: int
    applicant: str
    brand: str
    filename: str
    bucket: PairingBucket
    image: str | None = None
    candidate_filenames: list[str] = []
    errors: list[str] = []


class BatchStageSummary(BaseModel):
    matched: int = 0
    matched_fuzzy: int = 0
    missing_image: int = 0
    ambiguous: int = 0
    unused_images: list[str] = []


class StagedBatch(BaseModel):
    batch_id: str
    rows: list[StagedRow] = []
    summary: BatchStageSummary = BatchStageSummary()
    blocks_commit: bool = False


# Staged batches live until they are committed or the process restarts. Nothing
# is written to the store at stage time, so losing one costs a re-upload.
# ponytail: process-local dict; move to a table if staging ever needs to survive
# a restart or span two workers.
STAGED: dict[str, list[batching.Row]] = {}


def to_response(batch_id: str, rows: list[batching.Row], unused: list[str]) -> StagedBatch:
    summary = BatchStageSummary(unused_images=unused)
    for row in rows:
        setattr(summary, row.bucket, getattr(summary, row.bucket) + 1)
    return StagedBatch(
        batch_id=batch_id,
        rows=[
            StagedRow(
                row=r.row,
                applicant=r.applicant,
                brand=r.brand,
                filename=r.filename,
                bucket=r.bucket,
                image=r.image,
                candidate_filenames=r.candidate_filenames,
                errors=r.errors,
            )
            for r in rows
        ],
        summary=summary,
        blocks_commit=batching.blocks_commit(rows),
    )


@router.post("/batches/stage", response_model=StagedBatch)
def stage_batch(
    applications_csv: UploadFile = File(...),
    images: list[UploadFile] = File(default=[]),
) -> StagedBatch:
    try:
        rows = batching.parse_csv(applications_csv.file.read())
    except BatchCsvError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Images are written to the store now so a commit does not need the upload
    # again; an uncommitted batch just leaves unreferenced files behind, which
    # the next fixture reset clears.
    names = []
    for image in images:
        name = uploads.safe_basename(image.filename or "")
        if not name:
            continue
        (db.data_dir() / "images" / name).write_bytes(image.file.read())
        names.append(name)

    staged, unused = batching.pair(rows, names)
    batch_id = f"batch-{uuid.uuid4().hex[:8]}"
    STAGED[batch_id] = staged
    return to_response(batch_id, staged, unused)


def stage_sample_batch() -> StagedBatch:
    """The bundled 25-application sample batch, images already on disk (S4)."""
    rows = seed.read_applications()
    seed.copy_fixture_images()
    names = [r["filename"] for r in rows]
    staged, unused = batching.pair(rows, names)
    batch_id = f"sample-{uuid.uuid4().hex[:8]}"
    STAGED[batch_id] = staged
    return to_response(batch_id, staged, unused)
