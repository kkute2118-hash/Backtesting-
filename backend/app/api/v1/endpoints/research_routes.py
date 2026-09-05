"""AI panels, fundamental screens and the forex/crypto SMC engine."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status

from app.schemas.common import JobEnvelope
from app.schemas.product import DebateRequest, RowsRequest, ScreenRequest, SmcRequest
from app.services import ai, research

router = APIRouter()


@router.post("/ai/coach", response_model=JobEnvelope, status_code=status.HTTP_202_ACCEPTED)
def coach() -> Any:
    return ai.coach()


@router.get("/ai/coach/history")
def coach_history(limit: int = Query(default=10, ge=1, le=100)) -> dict[str, Any]:
    return ai.coach_history(limit)


@router.post("/ai/debate", response_model=JobEnvelope, status_code=status.HTTP_202_ACCEPTED)
def debate(payload: DebateRequest) -> Any:
    return ai.debate(payload.rows, capital=payload.capital, max_slots=payload.max_slots,
                     risk_pct=payload.risk_pct, target_count=payload.target_count,
                     max_candidates=payload.max_candidates)


@router.post("/ai/learning-panel", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def learning_panel() -> Any:
    return ai.learning_panel()


@router.get("/ai/learning-panel/history")
def panel_history(limit: int = Query(default=10, ge=1, le=100)) -> dict[str, Any]:
    return ai.panel_history(limit)


@router.post("/fundamentals/screens", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def screens(payload: ScreenRequest) -> Any:
    return research.run_screens(universes=payload.universes,
                                run_a=payload.run_a, run_b=payload.run_b)


@router.post("/fundamentals/candidates")
def fundamental_candidates(payload: RowsRequest) -> dict[str, Any]:
    return research.add_fundamental_candidates(payload.rows)


@router.post("/smc/scan", response_model=JobEnvelope, status_code=status.HTTP_202_ACCEPTED)
def smc_scan(payload: SmcRequest) -> Any:
    return research.smc_scan(pairs=payload.pairs, market=payload.market,
                             min_confluence=payload.min_confluence)


@router.post("/smc/candidates")
def smc_candidates(payload: RowsRequest) -> dict[str, Any]:
    return research.add_smc_candidates(payload.rows)


@router.get("/smc/learning")
def smc_learning(symbol: str | None = Query(default=None)) -> dict[str, Any]:
    return research.crypto_learning(symbol)
