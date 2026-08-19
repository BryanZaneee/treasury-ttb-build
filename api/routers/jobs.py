"""Job queue endpoints (PRD §5.1). Stub — worker pool lands in M5."""

from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(tags=["jobs"])


class JobCreateRequest(BaseModel):
    scope: Literal["pending", "batch"]
    batch_id: str | None = None
    verify_now: bool = False


class Job(BaseModel):
    id: str


@router.post("/jobs", response_model=Job, status_code=201)
def create_job(body: JobCreateRequest) -> Job:
    # M0: contract only — the bounded worker pool lands in M5.
    return Job(id="stub")


@router.get("/jobs/{job_id}/events")
def job_events(job_id: str) -> StreamingResponse:
    # M0: contract only — real progress/record/error events land in M5.
    async def _stub_stream() -> AsyncIterator[str]:
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(_stub_stream(), media_type="text/event-stream")
