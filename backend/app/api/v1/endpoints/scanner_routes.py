"""Scanner: runs, results, filtering, presets, the custom DSL and the radar."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status

from app.schemas.common import JobEnvelope, RunSummary
from app.schemas.scanner import (CustomStrategyRequest, CustomValidateRequest,
                                 FilteredResults, RadarRequest, ResultFilters,
                                 ScanRequest, SepaRequest)
from app.services import radar, scanner

router = APIRouter()


@router.post("/scanner/runs", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def start_scan(payload: ScanRequest) -> Any:
    """Start a scan. Scanning 2,000 stocks is minutes of work, so this returns
    a job id immediately and the result is fetched by run id."""
    return scanner.run_scan(
        universes=payload.universes, strategies=payload.strategies,
        min_score=payload.min_score, use_live_prices=payload.use_live_prices,
        limit=payload.limit, preset_id=payload.preset_id)


@router.get("/scanner/runs", response_model=list[RunSummary])
def list_scans(limit: int = Query(default=25, ge=1, le=100)) -> Any:
    return scanner.list_runs(limit=limit)


@router.get("/scanner/runs/{run_id}")
def get_scan(run_id: str) -> dict[str, Any]:
    return scanner.get_run(run_id)


@router.post("/scanner/runs/{run_id}/results", response_model=FilteredResults)
def filter_scan(run_id: str, filters: ResultFilters) -> Any:
    """Apply result filters server-side so the table, the export and the
    forward-test action all agree on which rows the user is looking at."""
    run = scanner.get_run(run_id)
    rows = run.get("rows", [])
    matched = scanner.filter_rows(rows, filters.model_dump())
    window = matched[filters.offset: filters.offset + filters.limit]
    return {
        "id": run_id,
        "status": run.get("status", "unknown"),
        "total": len(rows),
        "filtered": len(matched),
        "rows": window,
        "columns": run.get("columns", []),
        "stats": run.get("stats", {}),
        "confluence": scanner.confluence(matched),
    }


@router.post("/scanner/sepa", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def start_sepa(payload: SepaRequest) -> Any:
    return scanner.run_sepa(universes=payload.universes, min_score=payload.min_score,
                            max_stocks=payload.max_stocks,
                            apply_fundamental_screen=payload.apply_fundamental_screen)


@router.post("/scanner/custom/validate")
def validate_custom(payload: CustomValidateRequest) -> dict[str, Any]:
    """Parse the rule text without running it — the DSL is whitelist-only."""
    return scanner.validate_custom(payload.rules)


@router.post("/scanner/custom", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def start_custom(payload: CustomStrategyRequest) -> Any:
    return scanner.run_custom(
        universes=payload.universes, rules=payload.rules, backtest=payload.backtest,
        start_date=payload.start_date, end_date=payload.end_date,
        sl_pct=payload.sl_pct, target_r=payload.target_r)


@router.post("/radar/runs", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def start_radar(payload: RadarRequest) -> Any:
    return radar.run(universes=payload.universes, strategies=payload.strategies,
                     max_missing=payload.max_missing, min_readiness=payload.min_readiness)


@router.get("/radar/runs", response_model=list[RunSummary])
def list_radar(limit: int = Query(default=25, ge=1, le=100)) -> Any:
    return scanner.list_runs(kind=radar.RADAR_KIND, limit=limit)


@router.get("/radar/runs/{run_id}")
def get_radar(run_id: str) -> dict[str, Any]:
    return scanner.get_run(run_id)
