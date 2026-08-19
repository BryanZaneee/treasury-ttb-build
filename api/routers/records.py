"""Records endpoints (PRD §5.1).

Verify runs the M2 rules engine against a reader's label reading; the real
vision providers and the always-on OCR second reader land in M3 behind the
same `readers.Reader` protocol. Auto-close is deliberately absent: its
eligibility test (PRD §5.3) requires two readers agreeing, so with one reader
it could never pass.
"""

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Form, HTTPException, UploadFile
from pydantic import BaseModel

import adjudicate
import db
from config import settings
from models import Application, FieldResult, LabelReading, Record
from readers import get_reader

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
    record_id = db.next_record_id()
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
        # Client-supplied filename: keep the basename only, never a path.
        (db.data_dir() / "images" / Path(filename).name).write_bytes(image_bytes)
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


def read_specimen(specimen: str, image_path: Path) -> tuple[LabelReading, str]:
    """Read a specimen, falling back to local OCR when the reader fails.

    PRD §3.2: a reader that is unreachable, slow, or returns unparseable JSON
    degrades to the rules verdict, with the engine string recording the cause.
    The service never blocks on the reader (acceptance test 11).
    """
    path = image_path if image_path.exists() else Path("fixtures") / Path(specimen).name
    provider = settings.reader_provider

    try:
        reading = get_reader(provider).read(specimen, path)
        return reading, f"deterministic rules engine ({provider} reader)"
    except Exception as exc:  # noqa: BLE001 - any reader failure degrades, never 500s
        cause = type(exc).__name__ if not str(exc) else str(exc).split("\n")[0][:120]

    if provider == "ocr":
        raise HTTPException(status_code=422, detail=f"reader failed: {cause}")
    try:
        reading = get_reader("ocr").read(specimen, path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"no reader available: {exc}") from exc
    # An OCR-only reading never auto-closes (PRD §5.3); the engine string is
    # what tells the reviewer which reader actually read this label.
    return reading, f"deterministic rules engine ({provider} unreachable, read by OCR)"


def _application_from_row(row: sqlite3.Row) -> Application:
    return Application(
        brand=row["app_brand"],
        class_type=row["app_class_type"],
        abv=row["app_alcohol_content"],
        net=row["app_net_contents"],
        producer=row["app_producer"],
        origin=row["app_origin"],
        warning=bool(row["app_warning_declared"]),
    )


def disagreeing_fields(record_id: str) -> list[str]:
    return [
        r["field_key"] for r in db.get_field_results(record_id) if r["verdict"] != "match"
    ]


def enforce_override(record: sqlite3.Row, decision: str | None, override: bool) -> bool:
    """PRD §5.1: accepting a non-`match` verdict requires an explicit override.

    Deliberately its own function with its own test - the PRD calls out that
    this check must not end up buried in a generic field-merge loop, because
    that is how it gets lost in a refactor.
    """
    if decision != "accepted" or record["result"] == "match":
        return False
    fields = disagreeing_fields(record["id"])
    if not override:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "override_required",
                "message": (
                    "This record did not pass verification. Accepting it requires "
                    "an explicit override."
                ),
                "result": record["result"],
                "fields": fields,
            },
        )
    return True


@router.patch("/records/{record_id}", response_model=Record)
def patch_record(record_id: str, body: RecordPatchRequest) -> Record:
    row = db.get_record(record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="record not found")
    if body.application is not None and body.decision is not None:
        raise HTTPException(
            status_code=422,
            detail="edit the application or issue a decision, not both in one request",
        )
    # A decided record is not reopenable - the applicant files afresh and the
    # new record links back via supersedes_id (PRD §12).
    if row["decision"] is not None:
        raise HTTPException(
            status_code=409,
            detail="record is closed; a returned or accepted record is not reopenable",
        )

    if body.application is not None:
        app = body.application
        db.update_record(
            record_id,
            app_brand=app.brand,
            app_class_type=app.class_type,
            app_alcohol_content=app.abv,
            app_net_contents=app.net,
            app_producer=app.producer,
            app_origin=app.origin,
            app_warning_declared=app.warning,
            # Editing invalidates any prior verdict (PRD §5.1).
            verified=False,
            result=None,
            engine=None,
            quality=None,
            elapsed_ms=None,
            prep_ms=None,
            reader_ms=None,
            rules_ms=None,
        )
        db.clear_field_results(record_id)
        db.append_audit(record_id, "edited", app.model_dump())

    elif body.decision is not None:
        overridden = enforce_override(row, body.decision, body.override)
        decided_at = datetime.now(UTC).isoformat()
        db.update_record(
            record_id,
            decision=body.decision,
            decided_by=body.reviewer_name,
            decided_at=decided_at,
            override=overridden,
            note=body.reason,
        )
        db.append_audit(
            record_id,
            "decision",
            {
                "decision": body.decision,
                "decided_by": body.reviewer_name,
                "decided_at": decided_at,
                "override": overridden,
                "result": row["result"],
                "reason": body.reason,
            },
        )

    updated = db.get_record(record_id)
    assert updated is not None
    return _row_to_record(updated)


@router.post("/records/{record_id}/verify", response_model=Record)
def verify_record(record_id: str) -> Record:
    row = db.get_record(record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="record not found")

    specimen = row["specimen"] or row["filename"]
    started = time.perf_counter_ns()
    reading, engine = read_specimen(specimen, db.data_dir() / "images" / Path(specimen).name)
    read_done = time.perf_counter_ns()

    results, verdict = adjudicate.adjudicate(record_id, _application_from_row(row), reading)
    finished = time.perf_counter_ns()

    db.upsert_field_results(record_id, [r.model_dump(exclude={"record_id"}) for r in results])
    db.update_record(
        record_id,
        verified=True,
        result=verdict,
        quality=reading.quality,
        engine=engine,
        # Image preparation lands with the reader layer in M3; there is no prep
        # stage to measure yet, so reporting 0 is honest rather than invented.
        prep_ms=0,
        reader_ms=round((read_done - started) / 1_000_000),
        rules_ms=round((finished - read_done) / 1_000_000),
        elapsed_ms=round((finished - started) / 1_000_000),
        reader_provider=settings.reader_provider,
        reader_model=settings.reader_model,
        prompt_version=getattr(get_reader(settings.reader_provider), "prompt_version", None)
        if settings.reader_provider in ("openai", "gemini")
        else None,
    )
    db.append_audit(
        record_id,
        "verified",
        {
            "result": verdict,
            "engine": engine,
            "quality": reading.quality,
            "fields": {r.field_key: r.verdict for r in results},
        },
    )

    updated = db.get_record(record_id)
    assert updated is not None
    return _row_to_record(updated)
