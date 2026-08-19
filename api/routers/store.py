"""Fixture and store-import endpoints (PRD §5.1)."""

from typing import Literal

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import batching
import db
import seed
from config import settings
from csv_io import CsvImportError, from_csv
from routers.batches import StagedBatch, stage_sample_batch

router = APIRouter(tags=["store"])


class FixturesRequest(BaseModel):
    mode: Literal["stage", "reset"]


class FixturesResponse(BaseModel):
    mode: Literal["stage", "reset"]
    staged_count: int = 0
    reset_count: int = 0
    batch: StagedBatch | None = None


class StoreImportResponse(BaseModel):
    imported: int = 0
    skipped: int = 0


def _require_admin(authorization: str | None) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not settings.admin_token or token != settings.admin_token:
        raise HTTPException(status_code=401, detail="admin token required")


@router.get("/export/records.csv")
def export_records_csv() -> Response:
    """The CSV mirror (PRD §4.2). Caddy serves this straight off the data volume
    in production; locally there is no Caddy, so the API stands in."""
    db.write_mirror()
    return Response(
        content=(db.data_dir() / "records.csv").read_bytes(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="records.csv"'},
    )


@router.get("/export/template.csv")
def export_template_csv() -> Response:
    """A blank batch-intake CSV (S11). Header is the applicant-facing one from
    PRD §4.3, which is what batching.parse_csv accepts."""
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
    if body.mode == "reset":
        # ADMIN_TOKEN is checked here, not in TokenMiddleware, because the
        # requirement depends on the request body (PRD §5.1/§8) - "stage"
        # only needs the ACCESS_TOKEN the middleware already enforced.
        _require_admin(authorization)
        count = seed.reset_store()
        return FixturesResponse(mode="reset", reset_count=count)
    # "stage" previews the bundled sample batch (S4). Nothing is filed until a
    # job commits the returned batch_id.
    batch = stage_sample_batch()
    return FixturesResponse(mode="stage", staged_count=len(batch.rows), batch=batch)


@router.post("/store/import", response_model=StoreImportResponse)
def import_store(csv_file: UploadFile = File(...)) -> StoreImportResponse:
    data = csv_file.file.read()
    try:
        rows = from_csv(data)
    except CsvImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.snapshot(reason="import")
    imported = 0
    for row in rows:
        record_id = row.get("id") or f"imported-{imported}"
        db.insert_record(
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
                "app_warning_declared": row.get("app_warning_declared") == "True",
                "verified": row.get("verified") == "True",
                "result": row.get("result"),
                "elapsed_ms": row.get("elapsed_ms"),
                "engine": row.get("engine"),
                "decision": row.get("decision"),
                "decided_by": row.get("decided_by"),
                "decided_at": row.get("decided_at"),
                "note": row.get("note"),
            }
        )
        imported += 1
    return StoreImportResponse(imported=imported, skipped=0)
