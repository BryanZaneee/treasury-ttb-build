"""Records endpoints (PRD §5.1).

M0 stub: no store exists until M1, so every handler returns a correctly
shaped, empty-or-placeholder response rather than a 501 — this lets
openapi-typescript generate real TS types against the M0 API surface.
"""

from typing import Literal

from fastapi import APIRouter, Form, UploadFile
from pydantic import BaseModel

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


def _placeholder_record(record_id: str, body: RecordCreateRequest | None = None) -> Record:
    app = body.application if body else None
    return Record(
        id=record_id,
        received="",
        applicant=body.applicant if body else "",
        beverage=body.beverage if body else "",
        filename="",
        specimen=body.specimen_key or "" if body else "",
        app_brand=app.brand if app else "",
        app_class_type=app.class_type if app else "",
        app_alcohol_content=app.abv if app else "",
        app_net_contents=app.net if app else "",
        app_producer=app.producer if app else None,
        app_origin=app.origin if app else None,
        app_warning_declared=app.warning if app else False,
    )


@router.get("/records", response_model=RecordsListResponse)
def list_records(
    filter: FilterName | None = None,
    q: str | None = None,
    cursor: str | None = None,
) -> RecordsListResponse:
    return RecordsListResponse()


@router.post("/records", response_model=Record, status_code=201)
def create_record(
    applicant: str = Form(...),
    beverage: str = Form(...),
    application: str = Form(..., description="JSON-encoded Application"),
    specimen_key: str | None = Form(None),
    image: UploadFile | None = None,
) -> Record:
    # M0: multipart contract only — no image storage or DB write until M1.
    app = Application.model_validate_json(application)
    body = RecordCreateRequest(
        applicant=applicant,
        beverage=beverage,
        application=app,
        specimen_key=specimen_key,
    )
    return _placeholder_record("stub", body)


@router.get("/records/{record_id}", response_model=RecordDetail)
def get_record(record_id: str) -> RecordDetail:
    return RecordDetail(**_placeholder_record(record_id).model_dump())


@router.patch("/records/{record_id}", response_model=Record)
def patch_record(record_id: str, body: RecordPatchRequest) -> Record:
    return _placeholder_record(record_id)


@router.post("/records/{record_id}/verify", response_model=Record)
def verify_record(record_id: str) -> Record:
    return _placeholder_record(record_id)
