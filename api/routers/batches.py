"""Batch staging endpoint (PRD §5.1, §5.5). Stub — pairing lands in M5."""

from typing import Literal

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

router = APIRouter(tags=["batches"])

PairingBucket = Literal["matched", "matched_fuzzy", "missing_image", "ambiguous"]


class StagedRow(BaseModel):
    row: int
    applicant: str
    brand: str
    filename: str
    bucket: PairingBucket
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


@router.post("/batches/stage", response_model=StagedBatch)
def stage_batch(
    applications_csv: UploadFile = File(...),
    images: list[UploadFile] = File(default=[]),
) -> StagedBatch:
    # M0: contract only — CSV parsing and filename pairing land in M5.
    return StagedBatch(batch_id="stub")
