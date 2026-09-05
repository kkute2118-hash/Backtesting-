"""The separate research engines: fundamentals screens and forex/crypto SMC.

Both are deliberately kept out of the equity scanner's path. Fundamental
enrichment is expensive per symbol and would slow a whole-market scan to a
crawl, and the crypto/forex Smart Money Concepts engine builds its own learning
dataset rather than assuming the Indian-equity rules transfer.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.errors import ApiError, NotConfigured
from app.engine import core
from app.services import jobs
from app.services.jobs import JobHandle
from app.services.serialization import clean_value, frame_to_records

SCREEN_KIND = "fundamental_screens"
SMC_KIND = "smc_scan"


def _require_twelvedata() -> None:
    if not core.twelvedata_configured():
        raise NotConfigured(
            "This needs TWELVEDATA_API_KEY in the backend environment. The equity "
            "scanner, backtests and forward tests all work without it."
        )


def run_screens(*, universes: list[str], run_a: bool, run_b: bool) -> dict[str, Any]:
    _require_twelvedata()
    if not (run_a or run_b):
        raise ApiError("Select at least one screen to run.")
    # index_universe() is what the engine's screen walks, so the full-NSE option
    # (which comes from the Dhan master, not an index CSV) is not offered here.
    index_only = [u for u in universes if u != core.FULL_NSE_UNIVERSE]
    if not index_only:
        raise ApiError("Fundamental screens run over the Nifty index universes.")
    request = {"universes": index_only, "run_a": run_a, "run_b": run_b}

    def work(handle: JobHandle) -> dict[str, Any]:
        def report(done: int, total: int, symbol: str) -> None:
            handle.progress(done / max(1, total), f"Screening {symbol}")

        df = core.run_fundamental_screens(index_only, run_a=run_a, run_b=run_b,
                                          progress_cb=report)
        return {"rows": frame_to_records(df),
                "columns": [str(c) for c in (df.columns if df is not None else [])],
                "stats": {"results": 0 if df is None else len(df)},
                "request": request}

    return jobs.registry.submit(SCREEN_KIND, "Fundamental screens", work,
                                request=request, persist=True).to_public()


def add_fundamental_candidates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ApiError("Select at least one screened stock.")
    added = core.add_fundamental_forward_candidates(pd.DataFrame(rows))
    return {"added": int(added), "submitted": len(rows)}


def smc_scan(*, pairs: list[str], market: str, min_confluence: int) -> dict[str, Any]:
    _require_twelvedata()
    cleaned = [str(p).strip() for p in pairs if str(p).strip()]
    if not cleaned:
        raise ApiError("Add at least one pair, e.g. EUR/USD or BTC/USD.")
    if market not in {"Forex", "Crypto"}:
        raise ApiError("Market must be 'Forex' or 'Crypto'.")
    request = {"pairs": cleaned, "market": market, "min_confluence": min_confluence}

    def work(handle: JobHandle) -> dict[str, Any]:
        handle.progress(0.1, f"Fetching 4h and 15m data for {len(cleaned)} pair(s)")
        df = core.scan_smc_pairs(cleaned, market=market, min_confluence=min_confluence)
        return {"rows": frame_to_records(df),
                "columns": [str(c) for c in (df.columns if df is not None else [])],
                "stats": {"pairs": len(cleaned), "setups": 0 if df is None else len(df)},
                "request": request}

    return jobs.registry.submit(SMC_KIND, f"SMC scan — {market}", work,
                                request=request, persist=True).to_public()


def add_smc_candidates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ApiError("Select at least one SMC setup.")
    added = core.add_smc_forward_candidates(pd.DataFrame(rows))
    return {"added": int(added), "submitted": len(rows)}


def crypto_learning(symbol: str | None = None) -> dict[str, Any]:
    df = core.crypto_learning_summary(symbol)
    return {"rows": frame_to_records(df)}


def validate_pair(symbol: str, market: str) -> dict[str, Any]:
    _require_twelvedata()
    return {"symbol": symbol, "market": market,
            "valid": clean_value(core.td_validate_symbol(symbol, market))}
