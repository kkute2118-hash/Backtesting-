"""Stock detail: quote, candles, indicators, condition matrix, safety, SEPA."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.engine import core
from app.schemas.common import Timeframe
from app.services import charting, stocks

router = APIRouter()


@router.get("/stocks/search")
def search(q: str = Query(min_length=1), limit: int = Query(default=20, ge=1, le=100)) -> Any:
    return {"results": stocks.search(q, limit)}


@router.get("/stocks/{symbol}")
def detail(symbol: str, live: bool = Query(default=True)) -> dict[str, Any]:
    return stocks.quote(symbol, use_live=live)


@router.get("/stocks/{symbol}/history")
def history(symbol: str, timeframe: Timeframe = Query(default="1Y"),
            indicators: bool = Query(default=True)) -> dict[str, Any]:
    return stocks.history(symbol, timeframe, with_indicators=indicators)


@router.get("/stocks/{symbol}/indicators")
def indicators(symbol: str) -> dict[str, Any]:
    return stocks.indicators(symbol)


@router.get("/stocks/{symbol}/conditions")
def conditions(symbol: str,
               strategies: list[int] = Query(default=list(core.DEFAULT_STRATEGIES))
               ) -> dict[str, Any]:
    """Rule-by-rule pass/fail — the honest reason a stock did or did not qualify."""
    return stocks.condition_matrix(symbol, strategies)


@router.get("/stocks/{symbol}/signals")
def signals(symbol: str) -> dict[str, Any]:
    return stocks.signal_detail(symbol)


@router.get("/stocks/{symbol}/safety")
def safety(symbol: str, news: bool = Query(default=False)) -> dict[str, Any]:
    return stocks.safety_report(symbol, include_news=news)


@router.get("/stocks/{symbol}/dna")
def dna(symbol: str) -> dict[str, Any]:
    return stocks.dna(symbol)


@router.get("/stocks/{symbol}/fundamentals")
def fundamentals(symbol: str) -> dict[str, Any]:
    return stocks.fundamentals(symbol)


@router.get("/stocks/{symbol}/sepa")
def sepa(symbol: str) -> dict[str, Any]:
    return stocks.sepa_detail(symbol)


# ------------------------------------------------------- interactive chart
@router.get("/stocks/{symbol}/candles")
def candles(symbol: str, tf: str = Query(default="1D"),
            before: str | None = Query(default=None)) -> dict[str, Any]:
    """One page of candles for the chart; `before` is the previous page's
    `next_before` cursor."""
    return charting.candles(symbol, tf, before)


@router.get("/stocks/{symbol}/live")
def live_quote(symbol: str) -> dict[str, Any]:
    """The shared live quote; the open chart polls it every few seconds
    while the market is open."""
    return charting.live(symbol)
