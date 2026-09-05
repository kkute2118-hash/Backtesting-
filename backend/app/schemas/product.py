from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=400)


class WatchlistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=400)


class WatchlistSymbols(BaseModel):
    symbols: list[str] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=280)


class PresetConfig(BaseModel):
    universes: list[str] = Field(min_length=1)
    strategies: list[int] = Field(min_length=1)
    min_score: float = Field(default=85, ge=0, le=100)
    use_live_prices: bool = False
    limit: int | None = None


class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    config: PresetConfig


class PresetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    config: PresetConfig | None = None


class PreferenceUpdate(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: Any


class ForwardCandidates(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1)


class SyncRequest(BaseModel):
    universes: list[str] = Field(min_length=1)
    tail_days: int | None = Field(default=None, ge=1, le=90)


class FullSyncRequest(BaseModel):
    universes: list[str] = Field(min_length=1)
    period: str = "2 Years"


class LiveFeedRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class DebateRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1)
    capital: float | None = None
    max_slots: int | None = None
    risk_pct: float | None = None
    target_count: int = Field(default=5, ge=1, le=20)
    max_candidates: int = Field(default=15, ge=1, le=50)


class ScreenRequest(BaseModel):
    universes: list[str] = Field(min_length=1)
    run_a: bool = True
    run_b: bool = True


class SmcRequest(BaseModel):
    pairs: list[str] = Field(min_length=1)
    market: str = "Forex"
    min_confluence: int = Field(default=2, ge=0, le=6)


class RowsRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1)
