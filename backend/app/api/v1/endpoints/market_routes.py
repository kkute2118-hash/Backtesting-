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


@router.get("/universes")
def universes() -> dict[str, Any]:
    return {"universes": universe.choices()}
