"""Front-test scorecard: every paper-traded strategy against its backtest."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core import ttl_cache
from app.services import front_test

router = APIRouter()


@router.get("/front-test")
def scorecard() -> dict[str, Any]:
    return ttl_cache.cached("forward:front-test", 30, front_test.scorecard)
