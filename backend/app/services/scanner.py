"""The scanner: the product's core feature.

Every entry point here is a *job* (see ``services.jobs``) because a scan reads
hundreds to thousands of candle histories from SQLite and computes
multi-timeframe features over each. The engine call at the centre of each one -
``core.scan_dataset`` - is the same function the scheduled GitHub Actions job
runs after the close, so the API and the cron runner can never disagree about
what qualified.

Filtering is deliberately split in two:

* **scan inputs** (universe, strategies, live overlay) change what the engine
  evaluates and therefore require a new run;
* **result filters** (score, RSI, relative volume, safety, regime, sector...)
  are applied to a finished run's rows and are free to change.

That split is what stops a slider drag from re-scanning 2,000 stocks.
"""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from app.core.errors import ApiError, NotFound
from app.db import app_store
from app.engine import core
from app.services import jobs
from app.services.jobs import JobHandle
from app.services.serialization import clean_mapping, clean_value, frame_to_records
from app.services.universe import resolve

SCAN_KIND = "scan"
SEPA_KIND = "sepa"
CUSTOM_KIND = "custom"


# --------------------------------------------------------------------------- #
# shared loading
# --------------------------------------------------------------------------- #
def _load(handle: JobHandle, tickers: list[str], use_live_prices: bool) -> tuple[dict, str, int]:
    """Local candle load, optional live overlay, then the market regime.

    Zero Dhan calls unless ``use_live_prices`` is set: the whole point of the
    persistent store is that a scan does not re-download the market.
    """
    handle.progress(0.02, f"Loading local candles for {len(tickers):,} stocks")
    data = core.load_scan_dataset(tickers)
    if not data:
        raise ApiError(
            "The local candle store has no stock with 260+ bars for this universe. "
            "Build the history once from Data Manager before scanning."
        )

    if use_live_prices:
        if not core.dhan_configured():
            raise ApiError(
                "Live intraday prices need Dhan credentials. Turn the live overlay off "
                "to scan against the last stored close instead."
            )
        handle.progress(0.12, "Overlaying today's forming candle from the Dhan quote feed")
        try:
            data = core.attach_live_bars(data)
        except Exception as exc:
            raise ApiError(f"Could not fetch live intraday prices: {exc}") from exc

    handle.progress(0.18, "Reading market regime")
    proxy = max(data.values(), key=len)
    regime, regime_score = core.regime_from_index(proxy)
    return data, regime, int(regime_score)


def _progress_bridge(handle: JobHandle, start: float, end: float, label: str):
    span = end - start

    def report(fraction: float) -> None:
        handle.progress(start + span * max(0.0, min(1.0, float(fraction))), label)

    return report


# --------------------------------------------------------------------------- #
# the main scan
# --------------------------------------------------------------------------- #
def run_scan(*, universes: list[str], strategies: list[int], min_score: float,
             use_live_prices: bool, limit: int | None,
             preset_id: int | None = None) -> dict[str, Any]:
    """Submit a scan. Returns the job envelope; results arrive via the run id."""
    strategies = sorted({int(s) for s in strategies if int(s) in (1, 2, 3, 4)})
    if not strategies:
        raise ApiError("Select at least one strategy to scan.")
    tickers = resolve(universes)

    request = {
        "universes": universes, "strategies": strategies, "min_score": min_score,
        "use_live_prices": bool(use_live_prices), "limit": limit,
        "universe_size": len(tickers), "preset_id": preset_id,
    }

    def work(handle: JobHandle) -> dict[str, Any]:
        data, regime, regime_score = _load(handle, tickers, use_live_prices)
        stats: dict[str, Any] = {}
        handle.progress(0.2, f"Evaluating {len(data):,} stocks against "
                             f"{len(strategies)} strateg{'y' if len(strategies) == 1 else 'ies'}")
        result = core.scan_dataset(
            data, strategies, regime,
            progress_cb=_progress_bridge(handle, 0.2, 0.95, "Scanning"),
            stats=stats,
        )
        handle.progress(0.96, "Recording signals")
        persisted = 0
        if result is not None and not result.empty:
            try:
                persisted = core.persist_scanner_signals(result, min_score)
            except Exception:
                persisted = 0

        rows = frame_to_records(result)
        if limit:
            rows = sorted(rows, key=lambda r: r.get("Score") or 0, reverse=True)[: int(limit)]

        if preset_id is not None:
            _touch_preset(preset_id)

        return {
            "rows": rows,
            "columns": [str(c) for c in (result.columns if result is not None else [])],
            "stats": _scan_stats(stats, regime, regime_score, len(data), len(tickers)),
            "request": request,
        }

    job = jobs.registry.submit(SCAN_KIND, "Stock scan", work, request=request, persist=True)
    return job.to_public()


def _scan_stats(stats: dict, regime: str, regime_score: int,
                loaded: int, universe_size: int) -> dict[str, Any]:
    """Diagnostics the scanner tab shows, in a shape the UI can render directly."""
    signals = stats.get("signals", {}) or {}
    qualified = stats.get("qualified", {}) or {}
    audit = stats.get("safety_gate_audit")
    model = stats.get("ml_model")

    # train_win_probability_model() returns ready=False plus the sample count it
    # is still short of, which is exactly what the UI should say instead of
    # silently showing a blank Win Probability column.
    model_info: dict[str, Any] | None = None
    if isinstance(model, dict):
        model_info = {
            "ready": bool(model.get("ready")),
            "samples": clean_value(model.get("n_samples")),
            "min_samples": clean_value(model.get("min_samples")),
            "auc": clean_value(model.get("gbc_auc")),
            "brier": clean_value(model.get("gbc_brier")),
            "reason": clean_value(model.get("reason")),
        }

    return {
        "universe_size": universe_size,
        "loaded": loaded,
        "usable": int(stats.get("usable", 0) or 0),
        "too_short": int(stats.get("too_short", 0) or 0),
        "safety_gate_excluded": int(stats.get("safety_gate_excluded", 0) or 0),
        "regime": regime,
        "regime_score": regime_score,
        "per_strategy": [
            {"strategy": f"S{s}",
             "signals": int(signals.get(s, 0) or 0),
             "qualified": int(qualified.get(s, 0) or 0)}
            for s in sorted(set(list(signals.keys()) + list(qualified.keys())))
        ],
        "safety_gate_audit": frame_to_records(audit) if isinstance(audit, pd.DataFrame) else [],
        "ml_model": model_info,
    }


# --------------------------------------------------------------------------- #
# S4 SEPA
# --------------------------------------------------------------------------- #
def run_sepa(*, universes: list[str], min_score: float, max_stocks: int | None,
             apply_fundamental_screen: bool) -> dict[str, Any]:
    tickers = resolve(universes)
    request = {"universes": universes, "min_score": min_score,
               "max_stocks": max_stocks,
               "apply_fundamental_screen": bool(apply_fundamental_screen),
               "universe_size": len(tickers)}

    def work(handle: JobHandle) -> dict[str, Any]:
        handle.progress(0.05, f"Loading local candles for {len(tickers):,} stocks")
        data = core.load_scan_dataset(tickers)
        if not data:
            raise ApiError("No stock in this universe has 260+ stored bars yet.")
        handle.progress(0.3, "Applying the liquidity and price-action gate")
        results, audit = core.scan_s4_sepa(
            data, min_score=min_score, max_stocks=max_stocks,
            apply_fundamental_screen=apply_fundamental_screen,
        )
        handle.progress(0.95, "Formatting")
        return {
            "rows": frame_to_records(results),
            "columns": [str(c) for c in (results.columns if results is not None else [])],
            "stats": {"universe_size": len(tickers), "loaded": len(data),
                      "safety_gate_audit": frame_to_records(audit)
                      if isinstance(audit, pd.DataFrame) else []},
            "request": request,
        }

    job = jobs.registry.submit(SEPA_KIND, "S4 SEPA scan", work, request=request, persist=True)
    return job.to_public()


# --------------------------------------------------------------------------- #
# custom strategy DSL
# --------------------------------------------------------------------------- #
def validate_custom(text: str) -> dict[str, Any]:
    """Parse the rule text without running anything.

    The DSL is whitelist-only - never ``eval`` - so an unknown column is a
    validation error rather than an execution risk. The frontend calls this on a
    debounce to show errors while the user types.
    """
    conditions, errors = core.parse_custom_strategy(text or "")
    return {
        "valid": bool(conditions) and not errors,
        "conditions": [{"text": c["text"], "column": c["left"], "operator": c["op"]}
                       for c in conditions],
        "errors": errors,
        "columns": sorted(core.CUSTOM_DSL_COLUMNS),
        "operators": sorted(core.CUSTOM_DSL_OPS),
    }


def run_custom(*, universes: list[str], rules: str, backtest: bool,
               start_date: str | None, end_date: str | None,
               sl_pct: float, target_r: float) -> dict[str, Any]:
    conditions, errors = core.parse_custom_strategy(rules or "")
    if errors:
        raise ApiError("The rule set has errors: " + " ".join(errors))
    if not conditions:
        raise ApiError("Add at least one rule, e.g. 'rsi14 > 55'.")
    tickers = resolve(universes)
    request = {"universes": universes, "rules": rules, "backtest": bool(backtest),
               "start_date": start_date, "end_date": end_date,
               "sl_pct": sl_pct, "target_r": target_r, "universe_size": len(tickers)}

    def work(handle: JobHandle) -> dict[str, Any]:
        handle.progress(0.05, "Loading local candles")
        data = core.load_scan_dataset(tickers)
        if not data:
            raise ApiError("No stock in this universe has 260+ stored bars yet.")

        handle.progress(0.2, "Evaluating today's rule matches")
        rows = []
        total = max(1, len(data))
        for n, (ticker, df) in enumerate(data.items()):
            if n % 50 == 0:
                handle.progress(0.2 + 0.5 * n / total, "Evaluating rules")
            try:
                f = core.features_fast(str(ticker), df.sort_index())
                f = f.replace([float("inf"), float("-inf")], pd.NA)
                sig = core.custom_strategy_signal(f, conditions)
            except Exception:
                continue
            if len(sig) and bool(sig.iloc[-1]):
                z = f.iloc[-1]
                entry = float(z.close)
                rows.append({
                    "Ticker": str(ticker).replace(".NS", ""),
                    "Close": round(entry, 2),
                    "RSI": clean_value(getattr(z, "rsi14", None)),
                    "RelVol": clean_value(getattr(z, "relvol", None)),
                    "EMA20": clean_value(getattr(z, "ema20", None)),
                    "EMA50": clean_value(getattr(z, "ema50", None)),
                    "Entry": round(entry, 2),
                    "SL": round(entry * (1 - sl_pct), 2),
                    "Target": round(entry * (1 + sl_pct * target_r), 2),
                })

        backtest_payload: dict[str, Any] | None = None
        if backtest:
            handle.progress(0.75, "Backtesting the rule set")
            bt = core._custom_strategy_backtest(
                data, conditions,
                start_date or (pd.Timestamp.today() - pd.Timedelta(days=730)).date().isoformat(),
                end_date or pd.Timestamp.today().date().isoformat(),
                sl_pct=sl_pct, target_r=target_r,
            )
            backtest_payload = _backtest_payload(bt)

        return {
            "rows": rows,
            "columns": list(rows[0].keys()) if rows else [],
            "stats": {"universe_size": len(tickers), "loaded": len(data),
                      "conditions": [c["text"] for c in conditions]},
            "backtest": backtest_payload,
            "request": request,
        }

    job = jobs.registry.submit(CUSTOM_KIND, "Custom strategy", work,
                               request=request, persist=True)
    return job.to_public()


def _backtest_payload(bt: Any) -> dict[str, Any]:
    """Normalise the several shapes the engine's backtests return."""
    if bt is None:
        return {}
    if isinstance(bt, pd.DataFrame):
        return {"trades": frame_to_records(bt), "metrics": {}}
    if isinstance(bt, dict):
        out: dict[str, Any] = {}
        for key, value in bt.items():
            if isinstance(value, pd.DataFrame):
                out[key] = frame_to_records(value)
            else:
                out[key] = clean_value(value)
        return out
    return {"value": clean_value(bt)}


# --------------------------------------------------------------------------- #
# run access + result filtering
# --------------------------------------------------------------------------- #
def get_run(run_id: str) -> dict[str, Any]:
    job = jobs.registry.find(run_id)
    if job is not None and job.status not in jobs.TERMINAL:
        return {"id": run_id, "status": job.status, "progress": job.progress,
                "message": job.message, "request": job.request,
                "rows": [], "columns": [], "stats": {}, "error": None}

    if job is not None and job.status == jobs.SUCCEEDED and isinstance(job.result, dict):
        payload = dict(job.result)
        payload.update({"id": run_id, "status": job.status, "progress": 1.0,
                        "message": job.message, "error": None})
        return payload

    stored = jobs.load_run(run_id)
    if stored is None:
        if job is not None:
            return {"id": run_id, "status": job.status, "progress": job.progress,
                    "message": job.message, "request": job.request, "rows": [],
                    "columns": [], "stats": {}, "error": job.error}
        raise NotFound(f"Scan {run_id} was not found.")

    results = stored.get("results") or {}
    return {
        "id": run_id,
        "status": stored.get("status"),
        "progress": 1.0 if stored.get("status") in jobs.TERMINAL else 0.0,
        "message": stored.get("status"),
        "request": stored.get("request") or {},
        "rows": results.get("rows", []),
        "columns": results.get("columns", []),
        "stats": results.get("stats", {}),
        "backtest": results.get("backtest"),
        "error": stored.get("error"),
    }


def list_runs(kind: str | None = SCAN_KIND, limit: int = 25) -> list[dict[str, Any]]:
    return jobs.list_runs(kind=kind, limit=limit)


NUMERIC_FILTERS = {
    "min_score": ("Score", "gte"),
    "max_score": ("Score", "lte"),
    "min_rsi": ("RSI", "gte"),
    "max_rsi": ("RSI", "lte"),
    "min_relvol": ("RelVol", "gte"),
    "max_relvol": ("RelVol", "lte"),
    "min_price": ("Entry", "gte"),
    "max_price": ("Entry", "lte"),
    "min_win_probability": ("Win Probability %", "gte"),
    "min_safety": ("Safety Score", "gte"),
    "min_htf": ("HTF Score", "gte"),
    "min_footprint": ("Footprint Score", "gte"),
}


def filter_rows(rows: Iterable[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply result filters to a finished run.

    Kept server-side so the same predicate serves the table, the CSV export and
    the "send to forward test" action - three places that must agree on which
    rows the user is actually looking at.
    """
    out = list(rows)

    for key, (column, mode) in NUMERIC_FILTERS.items():
        bound = filters.get(key)
        if bound is None:
            continue
        bound = float(bound)
        kept = []
        for row in out:
            value = row.get(column)
            if value is None:
                continue
            if mode == "gte" and float(value) >= bound:
                kept.append(row)
            elif mode == "lte" and float(value) <= bound:
                kept.append(row)
        out = kept

    strategies = filters.get("strategies")
    if strategies:
        wanted = {str(s).upper() for s in strategies}
        out = [r for r in out
               if str(r.get("Strategy", "")).upper() in wanted
               or str(r.get("Strategy", "")).upper().startswith(tuple(wanted))]

    safety = filters.get("safety_status")
    if safety:
        wanted = {str(s).upper() for s in safety}
        out = [r for r in out if str(r.get("Safety", "")).upper() in wanted]

    search = (filters.get("search") or "").strip().upper()
    if search:
        out = [r for r in out if search in str(r.get("Ticker", "")).upper()]

    sort_by = filters.get("sort_by") or "Score"
    descending = filters.get("sort_dir", "desc") != "asc"

    def sort_key(row: dict[str, Any]):
        value = row.get(sort_by)
        if value is None:
            return (1, 0.0) if descending else (1, 0.0)
        if isinstance(value, (int, float)):
            return (0, float(value))
        return (0, str(value))

    try:
        numeric = all(isinstance(r.get(sort_by), (int, float, type(None))) for r in out)
        out = sorted(out,
                     key=lambda r: (r.get(sort_by) is None,
                                    r.get(sort_by) if numeric else str(r.get(sort_by) or "")),
                     reverse=descending)
    except TypeError:
        out = sorted(out, key=sort_key, reverse=descending)
    return out


def confluence(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stocks qualifying under more than one strategy at once."""
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_ticker.setdefault(str(row.get("Ticker")), []).append(row)
    out = []
    for ticker, group in by_ticker.items():
        if len(group) < 2:
            continue
        out.append({
            "Ticker": ticker,
            "Strategies": sorted({str(r.get("Strategy")) for r in group}),
            "Count": len(group),
            "Best Score": max(float(r.get("Score") or 0) for r in group),
            "Entry": group[0].get("Entry"),
            "Regime": group[0].get("Regime"),
            "Safety": group[0].get("Safety"),
        })
    return sorted(out, key=lambda r: (r["Count"], r["Best Score"]), reverse=True)


def _touch_preset(preset_id: int) -> None:
    try:
        con = app_store.connect()
        try:
            con.execute("UPDATE app_scanner_presets SET last_run_at=? WHERE id=?",
                        (pd.Timestamp.utcnow().isoformat(timespec="seconds"), int(preset_id)))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass
