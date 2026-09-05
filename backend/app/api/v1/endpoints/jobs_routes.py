"""Job status polling and cancellation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.schemas.common import JobEnvelope
from app.services import jobs

router = APIRouter()


@router.get("/jobs", response_model=list[JobEnvelope])
def list_jobs(kind: str | None = Query(default=None)) -> Any:
    return [job.to_public() for job in jobs.registry.list(kind)]


@router.get("/jobs/{job_id}", response_model=JobEnvelope)
def get_job(job_id: str) -> Any:
    return jobs.registry.get(job_id).to_public()


@router.post("/jobs/{job_id}/cancel", response_model=JobEnvelope)
def cancel_job(job_id: str) -> Any:
    """Ask a running job to stop at its next progress checkpoint."""
    return jobs.registry.cancel(job_id).to_public()
