"""Batch staging endpoint (PRD §5.1, §5.5).

Staging writes nothing. It parses the CSV, pairs images by filename, and returns
a preview with per-row buckets and errors. The staged batch is held until a job
commits it (`POST /api/jobs`).
"""

from __future__ import annotations

import json
import shutil
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


# Batch images are stored under their own basename, not the content-addressed
# key `uploads.store` produces: pairing is by filename, so the name is the
# thing being matched on and has to survive the write.
def _write_image(image: UploadFile) -> str | None:
    name = uploads.safe_basename(image.filename or "")
    if not name:
        return None
    images_dir = db.data_dir() / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / name).write_bytes(image.file.read())
    return name


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
        name = _write_image(image)
        if name:
            names.append(name)

    paired, _ = batching.pair(rows, names)
    batch_id = f"batch-{uuid.uuid4().hex[:8]}"
    return to_response(batch_id, put_staged(batch_id, Staged(rows=paired, images=names)))


def _require(batch_id: str) -> Staged:
    staged = get_staged(batch_id)
    if staged is None:
        raise HTTPException(status_code=404, detail=f"unknown batch {batch_id!r}")
    return staged


@router.get("/batches/{batch_id}", response_model=StagedBatch)
def read_batch(batch_id: str) -> StagedBatch:
    """Re-read a staged batch. A partial commit files some rows and leaves the
    rest, so the table needs a way to ask what is still staged."""
    return to_response(batch_id, _require(batch_id))


class AssignRequest(BaseModel):
    image: str | None = None


@router.post("/batches/{batch_id}/rows/{row_no}/image", response_model=StagedBatch)
def assign_image(batch_id: str, row_no: int, body: AssignRequest) -> StagedBatch:
    staged = _require(batch_id)
    try:
        batching.assign(staged.rows, staged.images, row_no, body.image)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("\"'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # `assign` mutates the rows in place, so the staged document has to be
    # written back - it is no longer the same object the next request loads.
    return to_response(batch_id, put_staged(batch_id, staged))


@router.post("/batches/{batch_id}/rows/{row_no}/upload", response_model=StagedBatch)
def upload_row_image(batch_id: str, row_no: int, image: UploadFile = File(...)) -> StagedBatch:
    """Supply the missing specimen for one staged row without re-uploading the
    batch - the reviewer has the file, it just was not in the folder."""
    staged = _require(batch_id)
    name = _write_image(image)
    if not name:
        raise HTTPException(status_code=422, detail="the upload has no filename")
    if name not in staged.images:
        staged.images.append(name)
    try:
        batching.assign(staged.rows, staged.images, row_no, name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("\"'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return to_response(batch_id, put_staged(batch_id, staged))


@router.delete("/batches/{batch_id}/images/{name}", response_model=StagedBatch)
def discard_image(batch_id: str, name: str) -> StagedBatch:
    """Drop an uploaded image the reviewer does not want in this batch. The
    file stays on disk; only the batch stops offering it."""
    staged = _require(batch_id)
    try:
        batching.discard(staged.rows, staged.images, uploads.safe_basename(name))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("\"'")) from exc
    return to_response(batch_id, put_staged(batch_id, staged))


@router.delete("/batches/{batch_id}/rows/{row_no}", response_model=StagedBatch)
def drop_row(batch_id: str, row_no: int) -> StagedBatch:
    """Drop a staged row before it is filed. A reviewer looking at a row they
    are not going to file - a duplicate, a withdrawn application, one with no
    specimen - should not have to re-upload the CSV without it."""
    staged = _require(batch_id)
    remaining = [r for r in staged.rows if r.row != row_no]
    if len(remaining) == len(staged.rows):
        raise HTTPException(status_code=404, detail=f"no row {row_no} in this batch")
    staged.rows = remaining
    return to_response(batch_id, put_staged(batch_id, staged))


# The sample batch is what a reviewer learns pairing on, so it arrives with one
# row in each state PRD §5.5 defines rather than 25 clean matches: a row whose
# image never arrived, a row named with the wrong extension, and a row two
# uploads both answer to. The rest match exactly.
_SAMPLE_MISSING = "tallgrass-cropped.jpg"
_SAMPLE_FUZZY = "quarry-house-units.jpg"
_SAMPLE_AMBIGUOUS = "ember-line-heavyblur.jpg"


def _sample_images(filenames: list[str]) -> list[str]:
    """The images "uploaded" with the sample batch - what is actually on disk,
    which is not quite what the CSV asks for."""
    images_dir = db.data_dir() / "images"
    names = [f for f in filenames if f != _SAMPLE_MISSING]

    # Two files that normalise to the same stem, and no exact match for either,
    # is what makes a row ambiguous (batching.stem).
    names.remove(_SAMPLE_AMBIGUOUS)
    source = images_dir / _SAMPLE_AMBIGUOUS
    for variant in (
        _SAMPLE_AMBIGUOUS.replace("-", "_"),
        _SAMPLE_AMBIGUOUS.replace("-", " "),
    ):
        if source.exists():
            shutil.copyfile(source, images_dir / variant)
        names.append(variant)
    return names


def stage_sample_batch() -> StagedBatch:
    """The bundled 25-application sample batch, images already on disk (S4)."""
    rows = seed.read_applications()
    seed.copy_fixture_images()
    # Built before the CSV is edited below: these are the files on disk.
    names = _sample_images([r["filename"] for r in rows])

    for row in rows:
        # The CSV names it .png; the file on disk is the .jpg beside it, which
        # is a fuzzy match rather than an exact one.
        if row["filename"] == _SAMPLE_FUZZY:
            row["filename"] = _SAMPLE_FUZZY.replace(".jpg", ".png")

    paired, _ = batching.pair(rows, names)
    batch_id = f"sample-{uuid.uuid4().hex[:8]}"
    return to_response(batch_id, put_staged(batch_id, Staged(rows=paired, images=names)))
