"""Batch staging endpoint (PRD §5.1, §5.5).

Staging writes nothing. It parses the CSV, pairs images by filename, and returns
a preview with per-row buckets and errors. The staged batch is held until a job
commits it (`POST /api/jobs`).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, TypeAdapter

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


# Staged batches are held as JSON documents rather than in a process dict: PRD
# §5 runs two workers, and a batch staged on one has to be committable by the
# other. Nothing lands in `records` until commit, so losing one costs a
# re-upload.
@dataclass
class Staged:
    rows: list[batching.Row]
    images: list[str]


_ROWS = TypeAdapter(list[batching.Row])


def get_staged(batch_id: str) -> Staged | None:
    body = db.doc_get("batch", batch_id)
    if body is None:
        return None
    raw = json.loads(body)
    return Staged(rows=_ROWS.validate_python(raw["rows"]), images=raw["images"])


def put_staged(batch_id: str, staged: Staged) -> Staged:
    db.doc_put(
        "batch",
        batch_id,
        json.dumps({"rows": _ROWS.dump_python(staged.rows, mode="json"), "images": staged.images}),
    )
    return staged


def to_response(batch_id: str, staged: Staged) -> StagedBatch:
    rows = staged.rows
    summary = BatchStageSummary(unused_images=batching.unused_images(rows, staged.images))
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

    paired, _ = batching.pair(rows, names)
    batch_id = f"batch-{uuid.uuid4().hex[:8]}"
    return to_response(batch_id, put_staged(batch_id, Staged(rows=paired, images=names)))


class AssignRequest(BaseModel):
    image: str | None = None


@router.post("/batches/{batch_id}/rows/{row_no}/image", response_model=StagedBatch)
def assign_image(batch_id: str, row_no: int, body: AssignRequest) -> StagedBatch:
    staged = get_staged(batch_id)
    if staged is None:
        raise HTTPException(status_code=404, detail=f"unknown batch {batch_id!r}")
    try:
        batching.assign(staged.rows, staged.images, row_no, body.image)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("\"'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # `assign` mutates the rows in place, so the staged document has to be
    # written back - it is no longer the same object the next request loads.
    return to_response(batch_id, put_staged(batch_id, staged))


def stage_sample_batch() -> StagedBatch:
    """The bundled 25-application sample batch, images already on disk (S4)."""
    rows = seed.read_applications()
    seed.copy_fixture_images()
    names = [r["filename"] for r in rows]
    paired, _ = batching.pair(rows, names)
    batch_id = f"sample-{uuid.uuid4().hex[:8]}"
    return to_response(batch_id, put_staged(batch_id, Staged(rows=paired, images=names)))
