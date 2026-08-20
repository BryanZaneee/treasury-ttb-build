"""Records endpoints (PRD §5.1).

Verify runs the rules engine against a reader's label reading, behind the
`readers.Reader` protocol. OCR is a fallback for when the vision reader is
unreachable, not the always-on second reader §5.3 describes, so the auto-close
gate here drops that spec's reader-agreement clause and keeps every other one -
see `_auto_close_eligible`.
"""

import hashlib
import random
import sqlite3
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Form, HTTPException, UploadFile
from pydantic import BaseModel

import adjudicate
import db
import logs
import uploads
from config import settings
from models import Application, FieldResult, LabelReading, Record
from readers import get_reader
from readers.prep import prepare
from readers.prompts import VERSION as PROMPT_VERSION
from readers.vision import SpendCapReached

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
) -> RecordsListResponse:
    rows = db.list_records(result_filter=filter, query=q)
    counts = db.filter_counts()
    return RecordsListResponse(
        records=[_row_to_record(r) for r in rows],
        counts=RecordCounts(**counts),
    )


@router.post("/records", response_model=Record, status_code=201)
def create_record(
    applicant: str = Form(...),
    beverage: str = Form(...),
    application: str = Form(..., description="JSON-encoded Application"),
    specimen_key: str | None = Form(None),
    verify_now: bool = Form(False),
    image: UploadFile | None = None,
) -> Record:
    app = Application.model_validate_json(application)

    # One source for the specimen, or the record carries an image it never reads.
    uploaded = image if image is not None and image.filename else None
    if uploaded is not None and specimen_key:
        raise HTTPException(
            status_code=422,
            detail="send an uploaded image or a specimen_key, not both",
        )
    if uploaded is None and not specimen_key:
        raise HTTPException(status_code=422, detail="an image or a specimen_key is required")

    record_id = db.next_record_id()
    filename = uploads.safe_basename(uploaded.filename or "") if uploaded else specimen_key or ""
    specimen = specimen_key or ""
    if uploaded is not None:
        try:
            specimen = uploads.store(uploaded.file.read(), db.data_dir() / "images")
        except uploads.UploadError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    record: dict[str, Any] = {
        "id": record_id,
        "received": datetime.now(UTC).isoformat(),
        "applicant": applicant,
        "beverage": beverage,
        "filename": filename,
        "specimen": specimen,
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
    db.insert_record(record)
    # Deviation from PRD §5.2, deliberate: nothing calls a reader on upload.
    # Extraction only happens when a reviewer asks for it, so a filing that is
    # never verified never costs a paid call.
    #
    # verify_now IS that ask - the single-label page's button reads "Submit for
    # verification". Running it here rather than as a second request from the
    # browser is what stops a reviewer who moves on from leaving a record that
    # nobody would ever verify.
    if verify_now:
        db.run_in_background(_verify_on_arrival, record_id)
    row = db.get_record(record_id)
    assert row is not None  # just inserted, must exist
    return _row_to_record(row)


def _verify_on_arrival(record_id: str) -> None:
    """Adjudicate a freshly filed record. Failures leave it pending, which is
    the state the inbox already knows how to show and a reviewer can retry."""
    try:
        verify_record(record_id)
    except Exception as exc:  # noqa: BLE001 - a filing must not fail on this
        logs.count("verify_on_arrival_errors")
        logs.event("verify_on_arrival_failed", record_id=record_id, detail=str(exc)[:200])


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


def read_specimen(specimen: str, image_path: Path) -> tuple[LabelReading, str, str, int]:
    """Read a specimen, falling back to local OCR when the reader fails.

    PRD §3.2: a reader that is unreachable, slow, or returns unparseable JSON
    degrades to the rules verdict, with the engine string recording the cause.
    The service never blocks on the reader (acceptance test 11).

    Returns the reading, the engine string, the reader that actually produced
    it - which after a fallback is not the one configured, and is what the UI
    uses to warn the reviewer that accuracy may be lower on a degraded capture -
    and the image-preparation time in milliseconds.
    """
    path = image_path if image_path.exists() else Path("fixtures") / Path(specimen).name
    provider = settings.reader_provider

    # Every reader prepares the same image through the same cached function, so
    # timing it here measures prep once and leaves the reader's call a cache
    # hit (PRD §5.4).
    prep_started = time.perf_counter_ns()
    with suppress(Exception):
        # An unreadable file is the reader's error to raise, with its own
        # fallback path; warming the cache is not where it should surface.
        prepare(path)
    prep_ms = round((time.perf_counter_ns() - prep_started) / 1_000_000)

    # PRD §5.2: the key carries the image hash and every setting that can change
    # a reading, so switching model or provider cannot serve the previous one.
    key: str | None = None
    with suppress(OSError):
        key = "|".join(
            [
                hashlib.sha256(path.read_bytes()).hexdigest(),
                PROMPT_VERSION,
                provider,
                settings.reader_model,
                settings.reader_effort,
            ]
        )
    if key is not None:
        cached = db.extraction_cache_get(key)
        if cached is not None:
            logs.count("cache_hits")
            return LabelReading(**cached["reading"]), cached["engine"], cached["reader"], prep_ms
    logs.count("cache_misses")

    try:
        reading = get_reader(provider).read(specimen, path)
        engine = f"rules check ({provider} reader)"
        if key is not None:
            # Only the configured reader's own answer is cached. A fallback
            # reading is degraded by definition and must not become sticky.
            db.extraction_cache_put(
                key,
                {"reading": reading.model_dump(mode="json"), "engine": engine, "reader": provider},
            )
        return reading, engine, provider, prep_ms
    except SpendCapReached:
        # Acceptance test 17: the engine string names the cause. "unavailable"
        # would read as an outage a reviewer should retry, when in fact nothing
        # is broken and nothing will change until the cap resets at UTC
        # midnight.
        logs.count("spend_cap_reached")
        capped = True
        cause = "daily paid-call cap reached"
    except Exception as exc:  # noqa: BLE001 - any reader failure degrades, never 500s
        logs.count("reader_errors")
        capped = False
        cause = type(exc).__name__ if not str(exc) else str(exc).split("\n")[0][:120]

    # The engine string a reviewer sees says only "unavailable" - which reader
    # failed and why is an operator question, and without this line the cause
    # was computed and thrown away, leaving a box that had silently degraded to
    # OCR with nothing in the journal to say what the provider actually
    # answered.
    logs.event("reader_fallback", provider=provider, model=settings.reader_model, cause=cause)
    if provider == "ocr":
        raise HTTPException(status_code=422, detail=f"reader failed: {cause}")
    try:
        reading = get_reader("ocr").read(specimen, path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"no reader available: {exc}") from exc
    # An OCR-only reading never auto-closes (PRD §5.3); the engine string is
    # what tells the reviewer which reader actually read this label.
    reason = "daily spend cap reached" if capped else f"{provider} unavailable"
    return (
        reading,
        f"rules check ({reason}, read by local OCR)",
        "ocr",
        prep_ms,
    )


def _auto_close_eligible(verdict: str, quality: str | None, reader_used: str) -> bool:
    """Whether a verified record may close itself (PRD §5.3, §8).

    Deviation from §5.3, deliberate: the spec's gate also requires the vision
    reader and OCR to agree on every field, which this service cannot answer
    because OCR is a fallback rather than an always-on second reader. Every
    other clause is enforced, and the whole thing stays behind
    AUTO_APPROVE_MATCHES, which is off unless an operator turns it on.
    """
    if not settings.auto_approve_matches or verdict != "match" or quality != "normal":
        return False
    # A record read only by the degraded fallback is one reader, and a
    # single-reader reading never auto-closes.
    if reader_used == "ocr":
        return False
    # §8: sample a fraction of eligible records into human review regardless,
    # so the policy is always being checked by somebody.
    return random.random() >= settings.qa_sample_rate


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


def enforce_override(
    record: sqlite3.Row, decision: str | None, override: bool, reviewer_name: str | None
) -> bool:
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
    # An override is the one decision where the audit row is the whole point, so
    # it may not be anonymous. PRD §8 accepts a free-text name because there is
    # no identity system; it does not accept no name at all.
    if not (reviewer_name or "").strip():
        raise HTTPException(
            status_code=422,
            detail={
                "error": "reviewer_name_required",
                "message": "Overriding a failed verification has to be attributed to a reviewer.",
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
        overridden = enforce_override(row, body.decision, body.override, body.reviewer_name)
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
    reading, engine, reader_used, prep_ms = read_specimen(
        specimen, db.data_dir() / "images" / Path(specimen).name
    )
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
        prep_ms=prep_ms,
        # Prep runs inside the reader call, so it is subtracted out rather than
        # double-counted across the two stages.
        reader_ms=max(0, round((read_done - started) / 1_000_000) - prep_ms),
        rules_ms=round((finished - read_done) / 1_000_000),
        elapsed_ms=round((finished - started) / 1_000_000),
        # The reader that actually read the label, which after a fallback is
        # not the configured one.
        reader_provider=reader_used,
        reader_model=settings.reader_model if reader_used != "ocr" else None,
        # Only a vision reading comes from a prompt, and it is the reader that
        # actually ran that fixes the version.
        prompt_version=PROMPT_VERSION if reader_used == "openai" else None,
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

    logs.count("verifications")
    logs.count(f"verdict_{verdict}")
    logs.event(
        "verified",
        record_id=record_id,
        result=verdict,
        reader=reader_used,
        quality=reading.quality,
        elapsed_ms=round((finished - started) / 1_000_000),
    )

    if _auto_close_eligible(verdict, reading.quality, reader_used):
        db.update_record(
            record_id,
            decision="accepted",
            decided_by="Automatic",
            decided_at=datetime.now(UTC).isoformat(),
        )
        # §8 requires an audit row per auto-close: an unattended decision has
        # to be as reviewable afterwards as a reviewer's own.
        db.append_audit(
            record_id,
            "auto_closed",
            {"result": verdict, "quality": reading.quality, "reader": reader_used},
        )
        logs.count("auto_closed")
        logs.event("auto_closed", record_id=record_id, reader=reader_used)

    updated = db.get_record(record_id)
    assert updated is not None
    return _row_to_record(updated)
