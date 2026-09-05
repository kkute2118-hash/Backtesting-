"""Forward-test book: positions, results, scorecard, signal log."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.schemas.product import ForwardCandidates
from app.services import forward

router = APIRouter()


@router.get("/forward/positions")
def positions(live: bool = Query(default=True)) -> dict[str, Any]:
    return forward.positions(use_live=live)


@router.get("/forward/summary")
def summary() -> dict[str, Any]:
    return {**forward.summary(), "totals": forward.book_totals()}


@router.get("/forward/results")
def results(limit: int = Query(default=500, ge=1, le=5000)) -> dict[str, Any]:
    return forward.results(limit)


@router.post("/forward/refresh")
def refresh() -> dict[str, Any]:
    """Resolve open positions against completed daily candles only."""
    return forward.refresh()


@router.post("/forward/candidates")
def add_candidates(payload: ForwardCandidates) -> dict[str, Any]:
    return forward.add_candidates(payload.rows)


@router.get("/scanner/signals")
def signals(limit: int = Query(default=500, ge=1, le=5000),
            signal_date: str | None = Query(default=None)) -> dict[str, Any]:
    return forward.signals(limit, signal_date)


@router.get("/live/forward")
def live_forward() -> dict[str, Any]:
    return forward.live_table()
