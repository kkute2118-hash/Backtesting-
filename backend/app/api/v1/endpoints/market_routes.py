"""Market overview, status, freshness and the universe catalogue."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services import market, universe

router = APIRouter()


@router.get("/market/overview")
def overview() -> dict[str, Any]:
    """One request for the whole dashboard."""
    return market.overview()


@router.get("/market/status")
def status() -> dict[str, Any]:
    return market.market_status()


@router.get("/market/freshness")
def freshness(universes: list[str] = Query(default=[])) -> dict[str, Any]:
    return market.freshness(universes=universes)


@router.get("/market/sector-strength")
def sector_strength(lookback_short: int = Query(default=21, ge=5, le=250),
                    lookback_mid: int = Query(default=63, ge=10, le=250),
                    lookback_long: int = Query(default=126, ge=20, le=500)
                    ) -> dict[str, Any]:
    """Which sectors are leading, over three windows rather than one."""
    return market.sector_strength((lookback_short, lookback_mid, lookback_long))


@router.post("/market/sector-sync")
def sector_sync() -> dict[str, Any]:
    """Fetch sector membership from the NSE constituent lists. No Dhan needed."""
    return market.sync_sectors()


@router.post("/market/index-sync")
def index_sync(years: int = Query(default=5, ge=1, le=15)) -> dict[str, Any]:
    """Fetch index OHLC from Dhan, so the market regime reads an index."""
    return market.sync_indices(years=years)


@router.get("/universes")
def universes() -> dict[str, Any]:
    return {"universes": universe.choices()}
