"""Market overview, status, freshness and the universe catalogue."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.core import ttl_cache
from app.services import market, universe

router = APIRouter()


# Short TTLs: these read the same SQLite tables the dashboard's other calls
# read, and the underlying answers change when a scan or a resolve finishes -
# both of which invalidate explicitly, so the TTL is a ceiling on staleness,
# not the mechanism.
OVERVIEW_TTL_SECONDS = 30
SECTOR_TTL_SECONDS = 120


@router.get("/market/overview")
def overview() -> dict[str, Any]:
    """One request for the whole dashboard."""
    return ttl_cache.cached("market:overview", OVERVIEW_TTL_SECONDS, market.overview)


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
    windows = (lookback_short, lookback_mid, lookback_long)
    return ttl_cache.cached(f"market:sector:{windows}", SECTOR_TTL_SECONDS,
                            lambda: market.sector_strength(windows))


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
