"""Adaptive learning, the statistical coach and the learning database."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services import learning

router = APIRouter()


@router.get("/learning/snapshot")
def snapshot(market: str = Query(default="INDIA"),
             limit: int = Query(default=500, ge=1, le=5000)) -> dict[str, Any]:
    return learning.snapshot(market, limit)


@router.get("/learning/edge")
def edge(market: str = Query(default="INDIA")) -> dict[str, Any]:
    """Score-band edge, shrunk toward neutral for small samples."""
    return learning.edge_table(market)


@router.get("/learning/components")
def components(market: str = Query(default="INDIA"),
               strategy: int | None = Query(default=None)) -> dict[str, Any]:
    return learning.component_weights(market, strategy)


@router.get("/learning/leaderboard")
def leaderboard() -> dict[str, Any]:
    return learning.leaderboard()


@router.get("/learning/model")
def model() -> dict[str, Any]:
    return learning.model_status()


@router.get("/learning/coach")
def coach(market: str = Query(default="INDIA"),
          strategy: str = Query(default="S1")) -> dict[str, Any]:
    return learning.coach(market, strategy)


@router.get("/learning/database")
def database() -> dict[str, Any]:
    return learning.database_stats()


@router.get("/learning/fingerprints")
def fingerprints(limit: int = Query(default=500, ge=1, le=5000)) -> dict[str, Any]:
    return learning.raw_fingerprints(limit)
