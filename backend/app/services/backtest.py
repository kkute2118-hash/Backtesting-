"""Walk-forward backtest, raw-signal capture, SL calibration and S4 studies.

All four read the local candle store and make zero Dhan calls — deliberately.
Acquiring history is an explicit Data Manager action; a research run that
silently downloaded would burn the rate limit and change its own inputs
mid-flight.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import pandas as pd

from app.core.errors import ApiError
from app.engine import core
from app.services import jobs
from app.services.jobs import JobHandle
from app.services.serialization import clean_value, frame_to_records
from app.services.universe import resolve

BACKTEST_KIND = "backtest"
RAW_KIND = "raw_signals"
SL_KIND = "sl_calibration"
S4_EXT_KIND = "s4_extension"
S4_RECOVERY_KIND = "s4_recovery"

PERIODS = {"6 Months": 183, "1 Year": 365, "2 Years": 730, "3 Years": 1095}


def period_window(period: str) -> tuple[date, date]:
    if period not in PERIODS:
        raise ApiError(f"Unknown period '{period}'. Use one of: {', '.join(PERIODS)}.")
    return core._bt_period(period)


def dataset_status(universes: list[str], period: str) -> dict[str, Any]:
    """How much of the requested window is actually available locally.

    Surfaced before the run because the honest answer is often "the backtest
    will cover 380 of your 500 stocks", and that changes how the result should
    be read.
    """
    tickers = resolve(universes)
    start, end = period_window(period)
    status = core.local_backtest_status(tickers, start, end)
    ready = int(status.Ready.sum()) if not status.empty else 0
    bars = int(status.Bars.sum()) if not status.empty else 0
    return {
        "period": period,
        "start": clean_value(start),
        "end": clean_value(end),
        "warmup_start": clean_value(core._bt_required_data_start(start)),
        "warmup_days": core.BT_WARMUP_DAYS,
        "universe_size": len(tickers),
        "ready": ready,
        "missing": max(0, len(status) - ready),
        "local_bars": bars,
        "rows": frame_to_records(status.head(500)) if not status.empty else [],
    }


def run(*, universes: list[str], period: str, threshold: float) -> dict[str, Any]:
    tickers = resolve(universes)
    start, end = period_window(period)
    request = {"universes": universes, "period": period, "threshold": threshold,
               "start": start.isoformat(), "end": end.isoformat(),
               "universe_size": len(tickers)}

    def work(handle: JobHandle) -> dict[str, Any]:
        handle.progress(0.05, "Checking the local dataset")
        started = time.perf_counter()
        try:
            handle.progress(0.15, f"Replaying {len(tickers):,} stocks over {period}")
            bt = core.run_local_backtest(tickers, start, end, int(threshold))
        except RuntimeError as exc:
            if str(exc) == "NO_LOCAL_DATA":
                raise ApiError(
                    "No local history covers this window. Sync the universe from Data "
                    "Manager, or pick a shorter period."
                ) from exc
            raise
        elapsed = time.perf_counter() - started

        handle.progress(0.9, "Recording the run")
        core._persist_backtest(bt, period, start, end, int(threshold), len(tickers), elapsed)
        learned = core._learn_from_backtest(bt)

        return {
            "rows": frame_to_records(bt),
            "columns": [str(c) for c in bt.columns],
            "stats": {
                **_backtest_stats(bt),
                "elapsed_seconds": round(elapsed, 2),
                "learning_observations_added": int(learned),
                "universe_size": len(tickers),
                "threshold": threshold,
                "period": period,
            },
            "request": request,
        }

    job = jobs.registry.submit(BACKTEST_KIND, f"Walk-forward backtest — {period}", work,
                               request=request, persist=True)
    return job.to_public()


def _backtest_stats(bt: pd.DataFrame) -> dict[str, Any]:
    if bt is None or bt.empty:
        return {"trades": 0, "by_strategy": [], "score_bands": []}

    by_strategy = []
    for strategy, group in bt.groupby("Strategy"):
        wins, losses = group[group.R > 0].R, group[group.R <= 0].R
        gross_win, gross_loss = float(wins.sum()), abs(float(losses.sum()))
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (99.99 if gross_win > 0 else 0)
        by_strategy.append({
            "strategy": str(strategy),
            "trades": len(group),
            "win_pct": round(float((group.R > 0).mean() * 100), 1),
            "avg_r": round(float(group.R.mean()), 3),
            "total_r": round(float(group.R.sum()), 2),
            "profit_factor": round(float(profit_factor), 2),
            "avg_return_pct": round(float(group["Return %"].mean()), 2),
            "avg_mfe_pct": round(float(group["MFE %"].mean()), 2),
            "avg_mae_pct": round(float(group["MAE %"].mean()), 2),
            "best_score": int(group.Score.max()),
        })

    bands = pd.cut(bt.Score, [84, 89, 94, 100], labels=["85-89", "90-94", "95-100"],
                   include_lowest=True)
    banded = bt.assign(Band=bands, Win=(bt.Outcome.str.upper() == "WIN").astype(int))
    learn = (banded.groupby("Band", observed=True)
             .agg(signals=("Ticker", "count"), wins=("Win", "sum"),
                  win_rate=("Win", "mean"), avg_r=("R", "mean"), total_r=("R", "sum"),
                  avg_return=("Return %", "mean"), avg_mfe=("MFE %", "mean"),
                  avg_mae=("MAE %", "mean"))
             .reset_index())
    if not learn.empty:
        learn["win_rate"] = (learn.win_rate * 100).round(1)
        for column in ("avg_r", "total_r", "avg_return", "avg_mfe", "avg_mae"):
            learn[column] = learn[column].round(2)
        learn["Band"] = learn["Band"].astype(str)

    return {
        "trades": len(bt),
        "by_strategy": sorted(by_strategy, key=lambda r: r["avg_r"], reverse=True),
        "score_bands": frame_to_records(learn),
    }


def latest() -> dict[str, Any]:
    """The most recent stored backtest, so the page is never empty on load."""
    bt, run_row = core._load_latest_backtest()
    if bt is None or bt.empty:
        return {"available": False, "rows": [], "columns": [], "stats": {}, "run": None}
    return {
        "available": True,
        "rows": frame_to_records(bt),
        "columns": [str(c) for c in bt.columns],
        "stats": _backtest_stats(bt),
        "run": [clean_value(v) for v in run_row] if run_row is not None else None,
    }


def portfolio(rows: list[dict[str, Any]], capital: float,
              risk_pct: float, slots: int) -> dict[str, Any]:
    """Fixed-fraction compounding over the backtest's realised R sequence."""
    frame = pd.DataFrame(rows)
    if frame.empty:
        bt, _run = core._load_latest_backtest()
        frame = bt
    if frame is None or frame.empty:
        raise ApiError("Run a backtest first — there are no trades to simulate.")
    result = core.portfolio_from_backtest(frame, float(capital), float(risk_pct), int(slots))
    return {str(k): clean_value(v) for k, v in result.items()}


# --------------------------------------------------------------------------- #
# research studies
# --------------------------------------------------------------------------- #
def _study_dataset(handle: JobHandle, tickers: list[str], start, end) -> dict:
    handle.progress(0.05, f"Loading local history for {len(tickers):,} stocks")
    data = core.load_local_backtest_data(tickers, start, end)
    if not data:
        raise ApiError(
            "No local history covers this window. Sync the universe from Data Manager first."
        )
    return data


def run_raw_signals(*, universes: list[str], period: str) -> dict[str, Any]:
    """Ungated capture: every S1-S4 signal simulated regardless of score.

    This is the dataset that makes it possible to ask whether the score
    predicts anything at all, rather than only ever seeing setups that already
    passed the gate.
    """
    tickers = resolve(universes)
    start, end = period_window(period)
    request = {"universes": universes, "period": period,
               "start": start.isoformat(), "end": end.isoformat(),
               "universe_size": len(tickers)}

    def work(handle: JobHandle) -> dict[str, Any]:
        data = _study_dataset(handle, tickers, start, end)
        handle.progress(0.2, "Simulating every raw signal")
        result = core.run_raw_signal_backtest(
            data, [1, 2, 3, 4], start, end,
            progress_cb=lambda f: handle.progress(0.2 + 0.7 * float(f), "Simulating"))
        handle.progress(0.95, "Persisting fingerprints")
        try:
            core._persist_raw_fingerprints(result, start, end, len(tickers))
        except Exception:
            pass
        return {
            "rows": frame_to_records(result, limit=5000),
            "columns": [str(c) for c in (result.columns if result is not None else [])],
            "stats": {"signals": 0 if result is None else len(result),
                      "universe_size": len(tickers), "period": period},
            "request": request,
        }

    job = jobs.registry.submit(RAW_KIND, "Raw strategy learning", work,
                               request=request, persist=True)
    return job.to_public()


def run_sl_calibration(*, universes: list[str], period: str) -> dict[str, Any]:
    """Compare stop-placement schemes over the same signals and the same bars."""
    tickers = resolve(universes)
    start, end = period_window(period)
    request = {"universes": universes, "period": period,
               "start": start.isoformat(), "end": end.isoformat(),
               "universe_size": len(tickers)}

    def work(handle: JobHandle) -> dict[str, Any]:
        data = _study_dataset(handle, tickers, start, end)
        handle.progress(0.2, "Walking every stop scheme forward")
        result = core.run_sl_calibration_study(
            data, [1, 2, 3, 4], start, end,
            progress_cb=lambda f: handle.progress(0.2 + 0.65 * float(f), "Calibrating"))
        handle.progress(0.9, "Aggregating")
        report = core.sl_calibration_report(result)
        try:
            core._persist_sl_calibration(result, start, end, len(tickers))
        except Exception:
            pass
        return {
            "rows": frame_to_records(report if isinstance(report, pd.DataFrame) else result,
                                     limit=2000),
            "columns": [str(c) for c in (report.columns
                                         if isinstance(report, pd.DataFrame) else [])],
            "stats": {"trades": 0 if result is None else len(result),
                      "schemes": sorted(core.SL_CALIBRATION_SCHEMES),
                      "universe_size": len(tickers), "period": period},
            "request": request,
        }

    job = jobs.registry.submit(SL_KIND, "Stop-loss calibration study", work,
                               request=request, persist=True)
    return job.to_public()


def run_s4_extension(*, universes: list[str], period: str,
                     sl_pct: float = 0.07, target_r: float = 3.0) -> dict[str, Any]:
    """Is the 3% EMA20 extension cutoff actually the best one? Measure it."""
    tickers = resolve(universes)
    start, end = period_window(period)
    request = {"universes": universes, "period": period, "sl_pct": sl_pct,
               "target_r": target_r, "universe_size": len(tickers)}

    def work(handle: JobHandle) -> dict[str, Any]:
        data = _study_dataset(handle, tickers, start, end)
        handle.progress(0.25, "Calibrating EMA20 extension buckets")
        cal = core.s4_ema20_extension_calibration(data, start, end,
                                                  sl_pct=sl_pct, target_r=target_r)
        report = core.s4_extension_bucket_report(cal)
        return {
            "rows": frame_to_records(report),
            "columns": [str(c) for c in (report.columns if report is not None else [])],
            "trades": frame_to_records(cal, limit=2000),
            "stats": {"signals": 0 if cal is None else len(cal),
                      "universe_size": len(tickers), "period": period},
            "request": request,
        }

    job = jobs.registry.submit(S4_EXT_KIND, "S4 EMA20 extension calibration", work,
                               request=request, persist=True)
    return job.to_public()


def run_s4_recovery(*, universes: list[str], period: str,
                    min_score: float = 70) -> dict[str, Any]:
    """The research-only S4 recovery study, kept separate from the S4 rules."""
    tickers = resolve(universes)
    start, end = period_window(period)
    request = {"universes": universes, "period": period, "min_score": min_score,
               "universe_size": len(tickers)}

    def work(handle: JobHandle) -> dict[str, Any]:
        data = _study_dataset(handle, tickers, start, end)
        handle.progress(0.25, "Walking the recovery study forward")
        result = core.study_s4_recovery_walkforward(data, start, end, min_score=min_score)
        metrics = core.research_metrics(result) if result is not None else {}
        return {
            "rows": frame_to_records(result, limit=2000),
            "columns": [str(c) for c in (result.columns if result is not None else [])],
            "stats": {"events": 0 if result is None else len(result),
                      "metrics": {str(k): clean_value(v) for k, v in (metrics or {}).items()},
                      "universe_size": len(tickers), "period": period},
            "request": request,
        }

    job = jobs.registry.submit(S4_RECOVERY_KIND, "S4 recovery study", work,
                               request=request, persist=True)
    return job.to_public()
