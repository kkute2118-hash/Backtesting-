"""Walk-forward backtest and the research studies."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status

from app.schemas.common import JobEnvelope, Period, RunSummary
from app.schemas.scanner import BacktestRequest, PortfolioRequest, StudyRequest
from app.services import backtest, scanner

router = APIRouter()


@router.get("/backtest/dataset")
def dataset(universes: list[str] = Query(default=["Nifty 500"]),
            period: Period = Query(default="1 Year")) -> dict[str, Any]:
    """How much of the requested window actually exists locally."""
    return backtest.dataset_status(universes, period)


@router.post("/backtest/runs", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def start_backtest(payload: BacktestRequest) -> Any:
    return backtest.run(universes=payload.universes, period=payload.period,
                        threshold=payload.threshold)


@router.get("/backtest/runs", response_model=list[RunSummary])
def list_backtests(limit: int = Query(default=25, ge=1, le=100)) -> Any:
    return scanner.list_runs(kind=backtest.BACKTEST_KIND, limit=limit)


@router.get("/backtest/runs/{run_id}")
def get_backtest(run_id: str) -> dict[str, Any]:
    return scanner.get_run(run_id)


@router.get("/backtest/latest")
def latest() -> dict[str, Any]:
    """The most recent stored backtest, so the page is never blank on load."""
    return backtest.latest()


@router.post("/backtest/portfolio")
def portfolio(payload: PortfolioRequest) -> dict[str, Any]:
    return backtest.portfolio(payload.rows, payload.capital, payload.risk_pct, payload.slots)


@router.post("/backtest/raw-signals", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def raw_signals(payload: StudyRequest) -> Any:
    return backtest.run_raw_signals(universes=payload.universes, period=payload.period)


@router.post("/backtest/sl-calibration", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def sl_calibration(payload: StudyRequest) -> Any:
    return backtest.run_sl_calibration(universes=payload.universes, period=payload.period)


@router.post("/backtest/s4-extension", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def s4_extension(payload: StudyRequest) -> Any:
    return backtest.run_s4_extension(universes=payload.universes, period=payload.period)


@router.post("/backtest/s4-recovery", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def s4_recovery(payload: StudyRequest) -> Any:
    return backtest.run_s4_recovery(universes=payload.universes, period=payload.period)
