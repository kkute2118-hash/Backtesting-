#!/usr/bin/env python3
"""Chart data for the trade-charts page: each strategy's backtest trades of
the last 12 months with the price around them.

    python scripts/trade_charts.py OUT_DIR [--days 365]

Writes OUT_DIR/s4.json, s5.json and s6.json. S4 and S5 come from
portfolio_bt.collect_trades (their own exits, the live entry filter and the
data guard replayed on the signal day); S6 from core.run_s6_backtest. Each
trade carries the closes from ~70 sessions before entry to 15 after exit,
the levels that decided it (stop, target, breakout level) and the exit guide
drawn over the holding period (S5: its 50-day EMA; S6: the 20% trail).
Read-only with respect to the database backup.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("GTF_DATA_DIR", tempfile.mkdtemp(prefix="trade-charts-"))
os.environ.setdefault("DB_BACKUP_REPO", "kkute2118-hash/Backtesting-")
os.environ.setdefault("DB_BACKUP_BRANCH", "db-backup")

from app.engine import core  # noqa: E402
from app.engine import portfolio_bt as pb  # noqa: E402

SHOW = 10                              # winners and losers charted per strategy
REASONS = {
    "S4_SEPA": {"WIN": "target hit", "LOSS": "stop hit", "TIMEOUT": "time exit", "OPEN": "still open"},
    "S5_POCKETPIVOT": {"50ema_violated": "closed below the 50-day EMA",
                       "initial_tight_stop_hit": "initial stop hit",
                       "max_hold_reached": "maximum hold reached", "OPEN": "still open"},
    "S6_BREAKOUT": {"TRAIL_STOP": "20% trailing exit", "STOP": "stop hit", "OPEN": "still open"},
}


def r2(v):
    return None if v is None or not np.isfinite(float(v)) else round(float(v), 2)


def trade_row(strategy, df, sym, sd, ed, entry, exit_, stop, reason, target=None, trigger=None):
    df = df.sort_index()
    i = df.index.searchsorted(pd.Timestamp(sd))
    j = min(df.index.searchsorted(pd.Timestamp(ed)), len(df) - 1)
    if i >= len(df):
        return None
    lo, hi = max(0, i - 70), min(len(df) - 1, j + 15)
    seg = df.iloc[lo:hi + 1]
    hold = df.close.iloc[i:j + 1]
    if strategy == "S6_BREAKOUT":
        guide = hold.cummax() * (1 - core.S6_TRAIL_PCT / 100)
    elif strategy == "S5_POCKETPIVOT":
        guide = df.close.ewm(span=50, adjust=False).mean().iloc[i:j + 1]
    else:
        guide = None
    ret = (exit_ / entry - 1) * 100
    risk = entry - stop
    return {
        "sym": sym, "entry_date": str(pd.Timestamp(sd).date()), "exit_date": str(pd.Timestamp(ed).date()),
        "entry": r2(entry), "exit": r2(exit_), "stop": r2(stop), "target": r2(target), "trigger": r2(trigger),
        "reason": REASONS[strategy].get(str(reason), str(reason)), "open": str(reason).upper() == "OPEN",
        "ret": round(ret, 2), "r": r2((exit_ - entry) / risk) if risk > 0 else None,
        "risk_pct": r2(risk / entry * 100),
        "days": int((pd.Timestamp(ed) - pd.Timestamp(sd)).days),
        "d": [str(x.date()) for x in seg.index], "c": [r2(v) for v in seg.close],
        "h": [r2(v) for v in seg.high], "l": [r2(v) for v in seg.low],
        "ei": int(i - lo), "xi": int(j - lo),
        "guide": [r2(v) for v in guide] if guide is not None else None,
    }


def summarise(rows):
    rets = [t["ret"] for t in rows]
    # Median, not mean: S5's initial stop can sit 0.1% under the entry, and one
    # such trade reads as hundreds of R.
    rs = [t["r"] for t in rows if t["r"] is not None]
    return {"trades": len(rows), "wins": sum(r > 0 for r in rets), "losses": sum(r <= 0 for r in rets),
            "avg_ret": round(float(np.mean(rets)), 2) if rets else None,
            "median_r": round(float(np.median(rs)), 2) if rs else None,
            "median_ret": round(float(np.median(rets)), 2) if rets else None,
            "open": sum(t["open"] for t in rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--days", type=int, default=365)
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    core.restore_db_from_github(force=True)
    core._persist_raw_fingerprints = lambda *a, **k: None
    con = core._db()
    try:
        syms = [r[0] for r in con.execute(
            "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' GROUP BY symbol HAVING COUNT(*) >= 260")]
    finally:
        con.close()
    data = core.load_scan_dataset(syms, lookback_days=1500)
    data = {k: v for k, v in data.items() if v is not None and len(v) >= 260}
    by_sym = {str(k).replace(".NS", ""): v for k, v in data.items()}
    end = pd.Timestamp(core.last_expected_nse_session())
    start = end - pd.Timedelta(days=args.days)

    trades = {s: [] for s in REASONS}
    t45 = pb.collect_trades(data, start, end, strategies=("S4_SEPA", "S5_POCKETPIVOT"))
    targets = {}
    s4raw = core.run_raw_signal_backtest(data, [4], start, end)
    for r in s4raw.itertuples():
        targets[(str(r.ticker).replace(".NS", ""), pd.Timestamp(r.signal_date).date())] = r.target
    for r in t45.itertuples():
        df = by_sym.get(r.symbol)
        if df is None:
            continue
        tgt = targets.get((r.symbol, pd.Timestamp(r.signal_date).date())) if r.strategy == "S4_SEPA" else None
        row = trade_row(r.strategy, df, r.symbol, r.entry_date, r.exit_date, float(r.entry), float(r.exit),
                        float(r.stop), r.exit_reason, target=tgt)
        if row:
            trades[r.strategy].append(row)

    s6 = core.run_s6_backtest(data, start, end)
    n = core.S6_BREAKOUT_LOOKBACK
    for _, r in s6.iterrows():
        df = by_sym[r["Ticker"]].sort_index()
        i = df.index.searchsorted(pd.Timestamp(r["Signal Date"]))
        trig = float(df.high.iloc[max(0, i - n):i].max())            # the 50-day high it broke
        row = trade_row("S6_BREAKOUT", df, r["Ticker"], r["Signal Date"], r["Exit Date"],
                        float(r["Entry"]), float(r["Exit"]), float(r["Initial SL"]),
                        r["Exit Reason"], trigger=trig)
        if row:
            trades["S6_BREAKOUT"].append(row)

    as_of = str(max(max(t["d"]) for rows in trades.values() for t in rows))
    for strat, rows in trades.items():
        # One position per stock, as the live book holds it: a trade that
        # starts while an earlier one in the same stock is still running is
        # the same move counted again.
        rows.sort(key=lambda t: t["entry_date"])
        busy, kept = {}, []
        for t in rows:
            if t["entry_date"] <= busy.get(t["sym"], ""):
                continue
            busy[t["sym"]] = t["exit_date"]
            # A trade the backtest closes on the last day of data is still open.
            if t["exit_date"] == as_of and not t["open"] and t["reason"] in (
                    "maximum hold reached", "time exit"):
                t["open"], t["reason"] = True, "still open"
            kept.append(t)
        rows[:] = kept
        rows.sort(key=lambda t: -t["ret"])
        losers = sorted([t for t in rows if t["ret"] < 0], key=lambda t: t["ret"])[:SHOW]
        payload = {"strategy": strat, "as_of": as_of, "from": str(start.date()),
                   "summary": summarise(rows), "winners": [t for t in rows if t["ret"] >= 0][:SHOW],
                   "losers": losers,
                   "best": rows[0]["sym"] if rows else None, "best_ret": rows[0]["ret"] if rows else None,
                   "worst": losers[0]["sym"] if losers else None,
                   "worst_ret": losers[0]["ret"] if losers else None}
        name = {"S4_SEPA": "s4", "S5_POCKETPIVOT": "s5", "S6_BREAKOUT": "s6"}[strat]
        (out / f"{name}.json").write_text(json.dumps(payload, separators=(",", ":")))
        print(name, payload["summary"], flush=True)


if __name__ == "__main__":
    main()
