"""Fixture and store-import endpoints (PRD §5.1)."""

from typing import Literal

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from pydantic import BaseModel

import db
import seed
from config import settings
from csv_io import CsvImportError, from_csv

router = APIRouter(tags=["store"])


class FixturesRequest(BaseModel):
    mode: Literal["stage", "reset"]


class FixturesResponse(BaseModel):
    mode: Literal["stage", "reset"]
    staged_count: int = 0
    reset_count: int = 0


class StoreImportResponse(BaseModel):
    imported: int = 0
    skipped: int = 0


def _require_admin(authorization: str | None) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not settings.admin_token or token != settings.admin_token:
        raise HTTPException(status_code=401, detail="admin token required")


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
    # "stage" previews the bundled sample batch without writing anything;
    # real staging logic (pairing, per-row buckets) is batching.py's job (M5).
    applications = seed.read_applications()
    return FixturesResponse(mode="stage", staged_count=len(applications))


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
