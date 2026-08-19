"""Fixture and store-import endpoints (PRD §5.1). Stub — land in M1."""

from typing import Literal

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

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


@router.post("/fixtures", response_model=FixturesResponse)
def fixtures(body: FixturesRequest) -> FixturesResponse:
    # M0: contract only — staging and reset (the latter additionally
    # requiring ADMIN_TOKEN per PRD §5.1/§8) land in M1.
    return FixturesResponse(mode=body.mode)


@router.post("/store/import", response_model=StoreImportResponse)
def import_store(csv_file: UploadFile = File(...)) -> StoreImportResponse:
    # M0: contract only — CSV import lands in M1.
    return StoreImportResponse()
