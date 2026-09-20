"""Forward-test book: positions, results, scorecard, signal log."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.schemas.product import ForwardCandidates
from app.core import ttl_cache
from app.services import forward

router = APIRouter()


@router.get("/forward/positions")
def positions(live: bool = Query(default=True)) -> dict[str, Any]:
    return forward.positions(use_live=live)


FORWARD_TTL_SECONDS = 30
SIGNALS_TTL_SECONDS = 60


@router.get("/forward/summary")
def summary() -> dict[str, Any]:
    return ttl_cache.cached(
        "forward:summary", FORWARD_TTL_SECONDS,
        lambda: {**forward.summary(), "totals": forward.book_totals()})


@router.get("/forward/results")
def results(limit: int = Query(default=500, ge=1, le=5000)) -> dict[str, Any]:
    return forward.results(limit)


@router.post("/forward/refresh")
def refresh() -> dict[str, Any]:
    """Resolve open positions against completed daily candles only."""
    outcome = forward.refresh()
    # A resolve is exactly the event the cached readings describe, so they are
    # dropped here rather than left to age out and show a book that no longer
    # matches the one the user just refreshed.
    ttl_cache.invalidate("forward:", "market:", "dashboard")
    return outcome


@router.post("/forward/candidates")
def add_candidates(payload: ForwardCandidates) -> dict[str, Any]:
    return forward.add_candidates(payload.rows)


@router.get("/scanner/signals")
def signals(limit: int = Query(default=500, ge=1, le=5000),
            signal_date: str | None = Query(default=None)) -> dict[str, Any]:
    return ttl_cache.cached(f"forward:signals:{limit}:{signal_date}",
                            SIGNALS_TTL_SECONDS,
                            lambda: forward.signals(limit, signal_date))


@router.get("/live/forward")
def live_forward() -> dict[str, Any]:
    return forward.live_table()
