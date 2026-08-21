"""Fixture and store-import endpoints (PRD §5.1)."""

import hmac
from typing import Any, Literal

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import batching
import csv_io
import db
import seed
from config import settings
from csv_io import CsvImportError, from_csv, parse_bool, unpack_field_results
from routers.batches import StagedBatch, stage_sample_batch

router = APIRouter(tags=["store"])


class FixturesRequest(BaseModel):
    mode: Literal["stage", "reset", "empty"]


class FixturesResponse(BaseModel):
    mode: Literal["stage", "reset", "empty"]
    staged_count: int = 0
    reset_count: int = 0
    batch: StagedBatch | None = None


class StoreImportResponse(BaseModel):
    imported: int = 0
    skipped: int = 0
    errors: list[str] = []


def _require_admin(authorization: str | None) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not settings.admin_token or not hmac.compare_digest(token, settings.admin_token):
        raise HTTPException(status_code=401, detail="admin token required")


# Generated here, not read off disk: the mirror is written by a debounced timer,
# so reading the file races that writer.
@router.get("/export/records.csv")
def export_records_csv() -> Response:
    """What a reviewer takes away; csv_io.REVIEW_COLUMNS says why not the mirror."""
    return Response(
        content=csv_io.to_review_csv(db.mirror_rows()),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="records.csv"'},
    )


@router.get("/export/backup.csv")
def export_backup_csv(authorization: str | None = Header(default=None)) -> Response:
    """The full mirror (PRD §4.2), which is what `POST /store/import` reads back.

    Admin-gated: unlike the reviewer export this carries applicant and reviewer
    names and free-text reasons, the fields logs.py redacts (PRD §8).
    """
    _require_admin(authorization)
    return Response(
        content=csv_io.to_csv(db.mirror_rows()),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="records-backup.csv"'},
    )


@router.get("/export/template.csv")
def export_template_csv() -> Response:
    """A blank batch-intake CSV (S11), headed as PRD §4.3 and parse_csv expect."""
    header = ",".join(batching.INTAKE_COLUMNS)
    return Response(
        content=f"{header}\n".encode(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="template.csv"'},
    )


@router.post("/fixtures", response_model=FixturesResponse)
def fixtures(
    body: FixturesRequest, authorization: str | None = Header(None)
) -> FixturesResponse:
    if body.mode == "empty":
        _require_admin(authorization)
        seed.empty_store()
        return FixturesResponse(mode="empty")
    if body.mode == "reset":
        # Checked here, not in TokenMiddleware, because it depends on the body
        # (PRD §5.1/§8) - "stage" needs only the ACCESS_TOKEN already enforced.
        _require_admin(authorization)
        count = seed.reset_store()
        return FixturesResponse(mode="reset", reset_count=count)
    # "stage" previews the sample batch (S4); nothing is filed until a job commits.
    batch = stage_sample_batch()
    return FixturesResponse(mode="stage", staged_count=len(batch.rows), batch=batch)


@router.post("/store/import", response_model=StoreImportResponse)
def import_store(
    csv_file: UploadFile = File(...),
    mode: Literal["merge", "replace"] = Form("merge"),
) -> StoreImportResponse:
    """Restore records from a CSV mirror (PRD §5.1, S11).

    Merge upserts by id, so re-importing an export is idempotent; replace wipes
    first, which is what makes the round trip byte-identical. Both snapshot.
    """
    data = csv_file.file.read()
    try:
        rows = from_csv(data)
    except CsvImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    records: list[dict[str, Any]] = []
    field_results: list[dict[str, Any]] = []
    errors: list[str] = []

    for index, row in enumerate(rows, start=1):
        record_id = (row.get("id") or "").strip()
        if not record_id:
            # A generated id would collide with the next import's, so a row
            # without one is an error, not a guess.
            errors.append(f"row {index}: no id")
            continue
        records.append(
            {
                "id": record_id,
                "received": row.get("received") or "",
                "applicant": row.get("applicant") or "",
                "beverage": row.get("beverage") or "",
                "filename": row.get("filename") or "",
                "specimen": row.get("specimen") or "",
                "quality": row.get("quality"),
                "app_brand": row.get("app_brand") or "",
                "app_class_type": row.get("app_class_type") or "",
                "app_alcohol_content": row.get("app_alcohol_content") or "",
                "app_net_contents": row.get("app_net_contents") or "",
                "app_producer": row.get("app_producer"),
                "app_origin": row.get("app_origin"),
                "app_warning_declared": parse_bool(row.get("app_warning_declared")),
                "verified": parse_bool(row.get("verified")),
                "result": row.get("result"),
                "elapsed_ms": _as_int(row.get("elapsed_ms")),
                "engine": row.get("engine"),
                "decision": row.get("decision"),
                "override": parse_bool(row.get("override")),
                "decided_by": row.get("decided_by"),
                "decided_at": row.get("decided_at"),
                "note": row.get("note"),
            }
        )
        field_results.extend(
            unpack_field_results(
                record_id,
                row.get("field_results") or "",
                row.get("field_notes") or "",
                row.get("field_values") or "",
            )
        )

    db.snapshot(reason=f"import-{mode}")
    if mode == "replace":
        db.wipe()
    db.upsert_records(records)
    for record_id in {r["record_id"] for r in field_results}:
        db.clear_field_results(record_id)
    db.upsert_field_results_many(field_results)
    db.append_audit(
        None, "import", {"mode": mode, "imported": len(records), "skipped": len(errors)}
    )
    return StoreImportResponse(imported=len(records), skipped=len(errors), errors=errors)


def _as_int(value: object) -> int | None:
    """CSV numbers arrive as strings; an INTEGER column should get an int."""
    text = str(value or "").strip()
    return int(text) if text.lstrip("-").isdigit() else None
