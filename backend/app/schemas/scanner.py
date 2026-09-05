from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import Period


class ScanRequest(BaseModel):
    universes: list[str] = Field(default_factory=lambda: ["Nifty 500"], min_length=1)
    strategies: list[int] = Field(default_factory=lambda: [1, 2, 3, 4], min_length=1)
    min_score: float = Field(default=85, ge=0, le=100)
    use_live_prices: bool = False
    limit: int | None = Field(default=None, ge=1, le=5000)
    preset_id: int | None = None

    @field_validator("strategies")
    @classmethod
    def _known_strategies(cls, value: list[int]) -> list[int]:
        bad = [s for s in value if s not in (1, 2, 3, 4)]
        if bad:
            raise ValueError(f"Unknown strategy: {bad}. The engine implements 1-4.")
        return sorted(set(value))


class SepaRequest(BaseModel):
    universes: list[str] = Field(default_factory=lambda: ["Nifty 500"], min_length=1)
    min_score: float = Field(default=60, ge=0, le=100)
    max_stocks: int | None = Field(default=None, ge=1)
    apply_fundamental_screen: bool = False


class CustomStrategyRequest(BaseModel):
    universes: list[str] = Field(default_factory=lambda: ["Nifty 500"], min_length=1)
    rules: str = Field(min_length=1)
    backtest: bool = False
    start_date: str | None = None
    end_date: str | None = None
    sl_pct: float = Field(default=0.07, gt=0, lt=1)
    target_r: float = Field(default=3.0, gt=0, le=20)


class CustomValidateRequest(BaseModel):
    rules: str = ""


class ResultFilters(BaseModel):
    """Post-scan filters. Changing these never re-runs the engine."""

    search: str | None = None
    strategies: list[str] | None = None
    safety_status: list[str] | None = None
    min_score: float | None = None
    max_score: float | None = None
    min_rsi: float | None = None
    max_rsi: float | None = None
    min_relvol: float | None = None
    max_relvol: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_win_probability: float | None = None
    min_safety: float | None = None
    min_htf: float | None = None
    min_footprint: float | None = None
    sort_by: str = "Score"
    sort_dir: Literal["asc", "desc"] = "desc"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=2000)


class FilteredResults(BaseModel):
    id: str
    status: str
    total: int
    filtered: int
    rows: list[dict[str, Any]]
    columns: list[str]
    stats: dict[str, Any] = Field(default_factory=dict)
    confluence: list[dict[str, Any]] = Field(default_factory=list)


class RadarRequest(BaseModel):
    universes: list[str] = Field(default_factory=lambda: ["Nifty 500"], min_length=1)
    strategies: list[int] = Field(default_factory=lambda: [1, 2, 3, 4], min_length=1)
    max_missing: int = Field(default=2, ge=0, le=6)
    min_readiness: float = Field(default=0, ge=0, le=100)


class BacktestRequest(BaseModel):
    universes: list[str] = Field(default_factory=lambda: ["Nifty 500"], min_length=1)
    period: Period = "1 Year"
    threshold: float = Field(default=85, ge=0, le=100)


class StudyRequest(BaseModel):
    universes: list[str] = Field(default_factory=lambda: ["Nifty 500"], min_length=1)
    period: Period = "1 Year"


class PortfolioRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    capital: float = Field(default=100000, gt=0)
    risk_pct: float = Field(default=1.0, gt=0, le=100)
    slots: int = Field(default=5, ge=1, le=50)
