#!/usr/bin/env python3
"""Build the data file behind the Claude dashboard page.

    python scripts/claude_dashboard.py OUT.json [--universe "Nifty 500"]

What it does, in order:
  1. Restores the newest database backup from GitHub into a throwaway
     directory (never the app's own data directory).
  2. Runs the scanner's three strategies (S4, S5, S6) over the stored candles,
     with today's live Dhan prices overlaid when the market is open and Dhan is
     reachable.
  3. Reads the forward-test book: open positions, closed results, and the
     per-strategy scorecard.
  4. Writes everything to OUT.json for the dashboard page to render.

It is READ-ONLY with respect to the backup. Nothing is enrolled, resolved or
pushed: forward testing belongs to the scheduled GitHub job
(.github/workflows/daily-forward-test.yml), and a second writer racing it for
the same backup would lose one side's changes.

Environment: GITHUB_TOKEN (or GH_TOKEN / GH_BACKUP_TOKEN) to read the backup.
DB_BACKUP_REPO / DB_BACKUP_BRANCH default to this repository's `db-backup`
branch, which is where the scheduled job pushes it. Dhan credentials are
optional; without them, or without network access to Dhan, the scan uses the
last stored close.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Must be set before core is imported: core picks its data directory and
# backup location at import time.
os.environ.setdefault("GTF_DATA_DIR", tempfile.mkdtemp(prefix="claude-dashboard-"))
os.environ.setdefault("DB_BACKUP_REPO", "kkute2118-hash/Backtesting-")
os.environ.setdefault("DB_BACKUP_BRANCH", "db-backup")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.engine import core  # noqa: E402

STRATEGIES = list(core.IMPLEMENTED_STRATEGIES)
BREADTH_HISTORY_SESSIONS = 120
CLOSED_RESULTS_LIMIT = 60

SIGNAL_COLUMNS = {
    "Ticker": "ticker", "Strategy": "strategy", "Entry": "entry", "SL 7%": "stop",
    "Target 3R": "target", "R:R": "exit_rule", "ATR %": "atr_pct",
    "Turnover Cr": "turnover_cr", "Sector Rank": "sector_rank", "Entry Filter": "entry_filter",
    "Score": "score", "RSI": "rsi", "RelVol": "relvol", "Safety": "safety",
}
POSITION_COLUMNS = {
    "Signal Date": "signal_date", "Ticker": "ticker", "Strategy": "strategy", "Entry": "entry",
    "Current Price": "price", "Gain/Loss %": "gain_pct", "Unrealized R": "r", "Stop": "stop",
    "Target": "target", "To Stop %": "to_stop_pct", "MFE %": "mfe_pct", "MAE %": "mae_pct",
    "Days Held": "days", "Price Source": "price_source", "Price As Of": "price_as_of",
}


def log(msg: str) -> None:
    print(f"[dashboard] {msg}", file=sys.stderr, flush=True)


def plain(v):
    """JSON-safe scalar: NaN/inf -> None, numpy -> python, dates -> ISO."""
    if v is None:
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v) if not isinstance(v, (int, str)) else v


def records(df: pd.DataFrame | None, columns: dict[str, str]) -> list[dict]:
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.iterrows():
        out.append({new: plain(r.get(old)) for old, new in columns.items() if old in df.columns})
    return out


def restore() -> int:
    if not core._github_configured():
        raise SystemExit("GitHub backup is not configured: set GITHUB_TOKEN (or GH_TOKEN).")
    core.restore_db_from_github(force=True)
    con = core._db()
    try:
        n = int(con.execute("SELECT COUNT(*) FROM candles").fetchone()[0])
    finally:
        con.close()
    if n == 0:
        raise SystemExit("Restored database holds no candles: "
                         + (getattr(core, "_GITHUB_LAST_ERROR", "") or "unknown reason"))
    log(f"restored backup: {n:,} candles")
    return n


def live_overlay(data: dict) -> tuple[dict, dict]:
    """Today's forming candle, if the market is open and Dhan answers."""
    status = {"used": False, "symbols": 0, "reason": ""}
    if not core.nse_market_is_open():
        status["reason"] = "market closed: using the last completed close"
        return data, status
    if not core.dhan_configured():
        status["reason"] = "no Dhan credentials: using the last stored close"
        return data, status
    try:
        merged, bars = core.attach_live_bars(data)
    except Exception as exc:  # network policy, token, rate limit
        status["reason"] = f"Dhan unreachable ({type(exc).__name__}): using the last stored close"
        return data, status
    if not bars:
        status["reason"] = "Dhan returned no live quotes: using the last stored close"
        return data, status
    status.update(used=True, symbols=len(bars), reason="live Dhan prices overlaid")
    return merged, status


def scan(universe: str) -> dict:
    tickers = core.resolve_universes([universe])
    data = core.load_scan_dataset(tickers)
    if not data:
        raise SystemExit("No stock in the restored store has enough history to scan.")
    data, live = live_overlay(data)
    proxy, proxy_src = core.market_regime_frame(data)
    regime, regime_score = core.regime_from_index(proxy)
    stats: dict = {}
    result = core.scan_dataset(data, STRATEGIES, regime, stats=stats)
    signals = records(result, SIGNAL_COLUMNS)
    signals.sort(key=lambda r: (str(r.get("strategy")), -(r.get("atr_pct") or 0)))
    log(f"scan: {len(data)} stocks, {len(signals)} signals, live={live['used']}")
    freshness = core.data_freshness_status(tickers)
    rejected = [{"ticker": plain(r.get("Ticker")), "strategy": plain(r.get("Strategy")),
                 "entry": plain(r.get("Entry")), "atr_pct": plain(r.get("ATR %")),
                 "turnover_cr": plain(r.get("Turnover Cr")), "sector_rank": plain(r.get("Sector Rank")),
                 "reason": plain(r.get("Entry Filter"))}
                for r in stats.get("rejected_rows", [])]
    return {
        "universe": universe,
        "stocks_scanned": len(data),
        "regime": regime,
        "regime_score": plain(regime_score),
        "regime_source": proxy_src,
        "live": live,
        "freshness": {k: plain(v) for k, v in freshness.items()},
        "per_strategy": [
            {"strategy": core.strategy_label_for(s),
             "raw_signals": int(stats.get("signals", {}).get(s, 0)),
             "qualified": int(stats.get("qualified", {}).get(s, 0)),
             "filtered_out": int(stats.get("entry_filter_reject", {}).get(s, 0))}
            for s in STRATEGIES
        ],
        "signals": signals,
        "filtered_out": rejected,
        "s6_watchlist": s6_watchlist(data),
    }


S6_WATCH_WITHIN_PCT = 8.0


def s6_watchlist(data: dict) -> list[dict]:
    """Stocks one good day away from an S6 signal.

    Every stock-level S6 rule passes (ATR, 52-week location), the close is
    within S6_WATCH_WITHIN_PCT of the prior 50-day high. A stock that broke out
    inside the re-arm window is kept, with the first date a new breakout would
    count as fresh. Any signal still needs market breadth >= the threshold on
    that day.
    """
    b = core.market_breakout_breadth()
    out = []
    for ticker, df in data.items():
        if df is None or len(df) < 260:
            continue
        x = core.attach_market_breadth(df, b)
        feats = core.strategy6_features(x)
        z = feats.iloc[-1]
        prior_hi = float(x.high.rolling(core.S6_BREAKOUT_LOOKBACK).max().shift(1).iloc[-1])
        close = float(x.close.iloc[-1])
        if not np.isfinite(prior_hi) or prior_hi <= 0:
            continue
        gap_pct = (prior_hi / close - 1) * 100            # <= 0: already above it today
        breakouts = x.close > x.high.rolling(core.S6_BREAKOUT_LOOKBACK).max().shift(1)
        past = breakouts.iloc[:-1]
        last_bo = past[past].index.max() if past.any() else None
        rearm = (last_bo + pd.Timedelta(days=core.S6_REARM_DAYS + 1)
                 if last_bo is not None and last_bo >= x.index[-1] - pd.Timedelta(days=core.S6_REARM_DAYS)
                 else None)
        ok = (gap_pct <= S6_WATCH_WITHIN_PCT
              and z.s6_atr_pct >= core.S6_MIN_ATR_PCT
              and z.s6_above_52w_low_pct >= core.S6_MIN_ABOVE_52W_LOW_PCT
              and z.s6_below_52w_high_pct <= core.S6_MAX_BELOW_52W_HIGH_PCT)
        if not ok:
            continue
        out.append({
            "ticker": str(ticker).replace(".NS", ""),
            "date": x.index[-1].date().isoformat(),
            "close": plain(close),
            "trigger": plain(prior_hi),
            "to_trigger_pct": plain(max(gap_pct, 0.0)),
            "eligible_from": rearm.date().isoformat() if rearm is not None else None,
            "stop_if_triggered": plain(prior_hi - core.S6_INITIAL_STOP_ATR * float(z.s6_atr)),
            "atr_pct": plain(z.s6_atr_pct),
            "above_52w_low_pct": plain(z.s6_above_52w_low_pct),
            "below_52w_high_pct": plain(z.s6_below_52w_high_pct),
        })
    out.sort(key=lambda r: (r.get("to_trigger_pct") or 0))
    return out


def breadth() -> dict:
    b = core.market_breakout_breadth()
    tail = b.dropna().tail(BREADTH_HISTORY_SESSIONS)
    return {
        "threshold": core.S6_MIN_BREADTH,
        "latest": plain(tail.iloc[-1]) if len(tail) else None,
        "latest_date": tail.index[-1].date().isoformat() if len(tail) else None,
        "history": [{"date": d.date().isoformat(), "value": plain(v)} for d, v in tail.items()],
    }


def forward() -> dict:
    live = core.nse_market_is_open() and core.dhan_configured()
    try:
        df, meta = core.forward_positions_view(use_live=live)
    except Exception as exc:
        log(f"live positions failed ({exc}); falling back to stored closes")
        df, meta = core.forward_positions_view(use_live=False)
    open_rows = records(df[df["Status"] == "ACTIVE"] if len(df) else df, POSITION_COLUMNS)
    open_rows.sort(key=lambda r: r.get("signal_date") or "", reverse=True)

    summary = core.forward_summary_table()
    scorecard = []
    for _, r in summary.iterrows():
        scorecard.append({
            "strategy": str(r["Strategy"]), "records": plain(r["Records"]), "open": plain(r["Open"]),
            "closed": plain(r["Closed"]), "wins": plain(r["Wins"]), "losses": plain(r["Losses"]),
            "win_pct": plain(r["Win %"]), "avg_r": plain(r["AvgR"]), "total_r": plain(r["TotalR"]),
            "status": plain(r["Status"]),
            "retired": str(r["Strategy"]).upper() in {f"S{s}" for s in core.RETIRED_STRATEGIES},
        })

    con = core._db()
    try:
        closed = pd.read_sql_query(
            """SELECT symbol, strategy, signal_date, entry, exit_price, result_r, return_pct,
                      outcome, holding_bars, closed_at
                 FROM forward_results ORDER BY closed_at DESC LIMIT ?""",
            con, params=(CLOSED_RESULTS_LIMIT,))
    finally:
        con.close()
    closed_rows = [{k: plain(v) for k, v in r.items()} for r in closed.to_dict("records")]
    return {"price_meta": {k: plain(v) for k, v in (meta or {}).items()},
            "open": open_rows, "closed": closed_rows, "scorecard": scorecard}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", help="where to write the dashboard JSON")
    ap.add_argument("--universe", default="Nifty 500", choices=core.UNIVERSE_CHOICES)
    args = ap.parse_args()

    restore()
    payload = {
        "generated_at": core.market_now().isoformat(timespec="minutes"),
        "market_open": bool(core.nse_market_is_open()),
        "last_completed_session": plain(core.latest_completed_nse_session()),
        "strategies": [core.strategy_label_for(s) for s in STRATEGIES],
        "rules": {
            "S6_BREAKOUT": {"min_breadth": core.S6_MIN_BREADTH, "stop_atr": core.S6_INITIAL_STOP_ATR,
                            "trail_pct": core.S6_TRAIL_PCT},
        },
        "scan": scan(args.universe),
        "breadth": breadth(),
        "forward": forward(),
    }
    Path(args.out).write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"wrote {args.out}")


if __name__ == "__main__":
    main()
