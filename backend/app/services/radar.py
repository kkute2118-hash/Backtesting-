"""Early Warning Radar — stocks approaching a trigger, not yet qualifying.

The daily scanner is binary: a stock is invisible until the day every rule of a
strategy passes, which is usually the day the move has already started. The
radar answers the other question, and it is a separate feature rather than a
looser scanner because it changes nothing about qualification - setting
``max_missing`` to 0 reproduces the scanner's qualified list exactly.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.errors import ApiError
from app.engine import core
from app.services import jobs
from app.services.jobs import JobHandle
from app.services.serialization import frame_to_records
from app.services.universe import resolve

RADAR_KIND = "radar"


def run(*, universes: list[str], strategies: list[int], max_missing: int,
        min_readiness: float) -> dict[str, Any]:
    strategies = sorted({int(s) for s in strategies if int(s) in (1, 2, 3, 4)})
    if not strategies:
        raise ApiError("Select at least one strategy for the radar.")
    tickers = resolve(universes)
    request = {"universes": universes, "strategies": strategies,
               "max_missing": max_missing, "min_readiness": min_readiness,
               "universe_size": len(tickers)}

    def work(handle: JobHandle) -> dict[str, Any]:
        handle.progress(0.05, f"Loading local candles for {len(tickers):,} stocks")
        data = core.load_scan_dataset(tickers)
        if not data:
            raise ApiError("No stock in this universe has 260+ stored bars yet.")
        handle.progress(0.15, "Reading market regime")
        proxy = max(data.values(), key=len)
        regime, _score = core.regime_from_index(proxy)

        stats: dict[str, Any] = {}

        def report(fraction: float) -> None:
            handle.progress(0.15 + 0.8 * float(fraction), "Measuring proximity and compression")

        df = core.early_warning_radar(
            data, strategies, regime,
            max_missing=max_missing, min_readiness=min_readiness,
            progress_cb=report, stats=stats,
        )
        summary = core.radar_missing_rule_summary(df)
        return {
            "rows": frame_to_records(df),
            "columns": [str(c) for c in (df.columns if df is not None else [])],
            "stats": {
                "universe_size": len(tickers),
                "loaded": len(data),
                "regime": regime,
                "scanned": int(stats.get("scanned", 0) or 0),
                "too_short": int(stats.get("too_short", 0) or 0),
                "feature_error": int(stats.get("feature_error", 0) or 0),
                "last_error": str(stats.get("last_error", "") or ""),
                "blocking_rules": frame_to_records(summary)
                if isinstance(summary, pd.DataFrame) else [],
            },
            "request": request,
        }

    job = jobs.registry.submit(RADAR_KIND, "Early warning radar", work,
                               request=request, persist=True)
    return job.to_public()
