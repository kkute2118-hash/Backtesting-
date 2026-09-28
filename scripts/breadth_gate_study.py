#!/usr/bin/env python3
"""What S6's market-breadth gate would do to every strategy.

    python scripts/breadth_gate_study.py OUT.json [--start 2022-01-01]

S6 only buys when market breadth (core.market_breakout_breadth: the 10-day sum
of the daily share of stocks closing above their prior 50-day high) is at
least core.S6_MIN_BREADTH. This asks what that gate is worth:

  * S4 and S5 trades (live entry filters replayed, as collect_trades does)
    split by the breadth on their signal day;
  * S6 replayed with the gate switched off, split the same way;
  * each result split 2022-24 / 2025-26 (the evidence rule in CLAUDE.md:
    a rule is adopted only if it holds on both);
  * the account-level result with Indian delivery costs, ₹1 lakh, one pool,
    with and without the gate applied to S4 and S5.

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

import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("GTF_DATA_DIR", tempfile.mkdtemp(prefix="breadth-gate-"))
os.environ.setdefault("DB_BACKUP_REPO", "kkute2118-hash/Backtesting-")
os.environ.setdefault("DB_BACKUP_BRANCH", "db-backup")

from app.engine import core  # noqa: E402
from app.engine import portfolio_bt as pb  # noqa: E402

BANDS = [(0.0, 0.25, "below 0.25"), (0.25, 0.50, "0.25-0.50"), (0.50, 99.0, "0.50 and above")]


def summary(t: pd.DataFrame) -> dict:
    if not len(t):
        return {"trades": 0}
    return {"trades": int(len(t)),
            "win_pct": round(float((t.ret > 0).mean() * 100), 1),
            "avg_pct": round(float(t.ret.mean()), 2),
            "median_pct": round(float(t.ret.median()), 2),
            "total_pct": round(float(t.ret.sum()), 0)}


def by_period(t: pd.DataFrame) -> dict:
    early = t[t.signal_date < "2025-01-01"]
    late = t[t.signal_date >= "2025-01-01"]
    return {"all": summary(t), "2022-24": summary(early), "2025-26": summary(late)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--start", default="2022-01-01")
    args = ap.parse_args()

    core.restore_db_from_github(force=True)
    core._persist_raw_fingerprints = lambda *a, **k: None
    con = core._db()
    try:
        syms = [r[0] for r in con.execute(
            "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' GROUP BY symbol HAVING COUNT(*) >= 260")]
    finally:
        con.close()
    data = core.load_scan_dataset(syms, lookback_days=2600)
    end = str(core.last_expected_nse_session())
    breadth = core.market_breakout_breadth(force=True)
    thr = core.S6_MIN_BREADTH

    trades = pb.collect_trades(data, args.start, end)
    long_data = {k: v for k, v in data.items() if v is not None and len(v) >= 260}
    ungated = core.run_s6_backtest(long_data, args.start, end,
                                   breadth=pd.Series(1.0, index=breadth.index))
    s6_all = pd.DataFrame({
        "strategy": "S6_BREAKOUT (no gate)", "symbol": ungated["Ticker"], "signal_date": ungated["Signal Date"],
        "entry_date": ungated["Entry Date"], "entry": ungated["Entry"], "stop": ungated["Initial SL"],
        "exit_date": ungated["Exit Date"], "exit": ungated["Exit"], "exit_reason": ungated["Exit Reason"],
        "rank_key": ungated["ATR %"]})
    every = pd.concat([trades, s6_all], ignore_index=True)
    every = every[every.exit_reason.astype(str).str.upper() != "OPEN"].copy()
    every["signal_date"] = pd.to_datetime(every.signal_date)
    every["breadth"] = breadth.reindex(every.signal_date.values, method="ffill").values
    every["ret"] = (every.exit / every.entry - 1) * 100

    out = {"threshold": thr, "window": f"{args.start} to {end}, closed trades, gross returns",
           "strategies": {}}
    for strat, g in every.groupby("strategy"):
        row = {"all": by_period(g), "bands": {}}
        for lo, hi, name in BANDS:
            row["bands"][name] = by_period(g[(g.breadth >= lo) & (g.breadth < hi)])
        row["gate_on"] = by_period(g[g.breadth >= thr])
        row["gate_off_days"] = by_period(g[g.breadth < thr])
        out["strategies"][strat] = row

    # Account level: one ₹1 lakh pool, costs on, 10 slots, 1% risk.
    closes = pb.close_matrix(data)
    def account(t):
        r = pb.run_portfolio(t, closes, capital=100_000, max_positions=10, risk_pct=1.0,
                             costs=pb.IndianDeliveryCosts(), start=args.start, end=end)
        return {k: r.stats[k] for k in ("final", "cagr_pct", "max_drawdown_pct", "trades", "win_pct")}
    trades = trades.copy()
    trades["signal_date"] = pd.to_datetime(trades.signal_date)
    trades["breadth"] = breadth.reindex(trades.signal_date.values, method="ffill").values
    gated = trades[(trades.strategy == "S6_BREAKOUT") | (trades.breadth >= thr)]
    out["account"] = {
        "S4+S5+S6 as today": account(trades),
        "S4+S5+S6, gate on S4 and S5 too": account(gated),
        "S4+S5 as today": account(trades[trades.strategy != "S6_BREAKOUT"]),
        "S4+S5 with the gate": account(gated[gated.strategy != "S6_BREAKOUT"]),
        "S6 alone": account(trades[trades.strategy == "S6_BREAKOUT"]),
    }
    days = breadth[breadth.index >= pd.Timestamp(args.start)].dropna()
    out["share_of_days_gate_open_pct"] = round(float((days >= thr).mean() * 100), 1)

    Path(args.out).write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
