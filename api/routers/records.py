"""Records endpoints (PRD §5.1).

GET/create/read are DB-backed (M1). Verify and decision-issuing PATCH stay
contract-only stubs until the rules engine (M2) and reader layer (M3) exist
to actually produce a verdict - wiring them now would mean inventing the
verdict logic here instead of in adjudicate.py, which is a separate milestone.
"""

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Form, HTTPException, UploadFile
from pydantic import BaseModel

import db
from models import Application, FieldResult, Record

router = APIRouter(tags=["records"])

FilterName = Literal["attention", "pending", "review", "fail", "closed"]


class RecordCounts(BaseModel):
    attention: int = 0
    pending: int = 0
    review: int = 0
    fail: int = 0
    closed: int = 0


class RecordsListResponse(BaseModel):
    records: list[Record] = []
    counts: RecordCounts = RecordCounts()
    cursor: str | None = None


class RecordDetail(Record):
    field_results: list[FieldResult] = []


class RecordCreateRequest(BaseModel):
    applicant: str
    beverage: str
    application: Application
    specimen_key: str | None = None


class RecordPatchRequest(BaseModel):
    application: Application | None = None
    decision: Literal["accepted", "returned"] | None = None
    override: bool = False
    reviewer_name: str | None = None
    reason: str | None = None


def _row_to_record(row: sqlite3.Row) -> Record:
    # sqlite3.Row iterates its *values*, not column names - .keys() is required here,
    # not the redundant call SIM118 assumes for a plain dict.
    return Record(**{col: row[col] for col in row.keys() if col in Record.model_fields})  # noqa: SIM118


@router.get("/records", response_model=RecordsListResponse)
def list_records(
    filter: FilterName | None = None,
    q: str | None = None,
    cursor: str | None = None,
) -> RecordsListResponse:
    rows = db.list_records(result_filter=filter, query=q)
    counts = db.filter_counts()
    return RecordsListResponse(
        records=[_row_to_record(r) for r in rows],
        counts=RecordCounts(**counts),
        cursor=None,
    )


@router.post("/records", response_model=Record, status_code=201)
def create_record(
    applicant: str = Form(...),
    beverage: str = Form(...),
    application: str = Form(..., description="JSON-encoded Application"),
    specimen_key: str | None = Form(None),
    image: UploadFile | None = None,
) -> Record:
    app = Application.model_validate_json(application)
    record_id = f"COLA-{uuid.uuid4().hex[:8].upper()}"
    filename = (image.filename if image else None) or specimen_key or ""
    record: dict[str, Any] = {
        "id": record_id,
        "received": datetime.now(UTC).isoformat(),
        "applicant": applicant,
        "beverage": beverage,
        "filename": filename,
        "specimen": specimen_key or filename,
        "quality": None,
        "app_brand": app.brand,
        "app_class_type": app.class_type,
        "app_alcohol_content": app.abv,
        "app_net_contents": app.net,
        "app_producer": app.producer,
        "app_origin": app.origin,
        "app_warning_declared": app.warning,
        "verified": False,
        "result": None,
    }
    if image is not None:
        image_bytes = image.file.read()
        (db.data_dir() / "images" / filename).write_bytes(image_bytes)
    db.insert_record(record)
    row = db.get_record(record_id)
    assert row is not None  # just inserted, must exist
    return _row_to_record(row)


@router.get("/records/{record_id}", response_model=RecordDetail)
def get_record(record_id: str) -> RecordDetail:
    row = db.get_record(record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="record not found")
    field_rows = db.get_field_results(record_id)
    return RecordDetail(
        **_row_to_record(row).model_dump(),
        field_results=[FieldResult(**dict(r)) for r in field_rows],
    )


@router.patch("/records/{record_id}", response_model=Record)
def patch_record(record_id: str, body: RecordPatchRequest) -> Record:
    # M1: contract only. Field edits and the accept/override enforcement rule
    # (PRD §5.1) land once M2's rules engine can re-derive a verdict.
    row = db.get_record(record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="record not found")
    return _row_to_record(row)


@router.post("/records/{record_id}/verify", response_model=Record)
def verify_record(record_id: str) -> Record:
    # M1: contract only - real verification needs adjudicate.py (M2) and a
    # reader (M3).
    row = db.get_record(record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="record not found")
    return _row_to_record(row)
