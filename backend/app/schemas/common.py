"""Request and response models shared across the API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Period = Literal["6 Months", "1 Year", "2 Years", "3 Years"]
Timeframe = Literal["1M", "3M", "6M", "1Y", "2Y", "5Y", "MAX"]


class JobEnvelope(BaseModel):
    """Every long-running action answers with this, not with its result."""

    id: str
    kind: str
    label: str
    status: str
    progress: float
    message: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)


class RunResult(BaseModel):
    """A finished (or still running) job's payload."""

    model_config = ConfigDict(extra="allow")

    id: str
    status: str
    progress: float = 0.0
    message: str | None = None
    error: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    id: str
    kind: str
    created_at: str
    finished_at: str | None = None
    status: str
    row_count: int = 0
    error: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)


class Acknowledged(BaseModel):
    ok: bool = True
    message: str | None = None
