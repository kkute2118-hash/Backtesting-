#!/usr/bin/env python3
"""Replay S4/S5/S6 through an account, with Indian delivery costs.

    python scripts/portfolio_backtest.py OUT.json [--capital 100000] [--slots 10]
        [--strategies S4_SEPA,S5_POCKETPIVOT,S6_BREAKOUT] [--buckets S5_POCKETPIVOT=1,S6_BREAKOUT=1]
        [--risk 1] [--start 2022-01-01] [--no-costs] [--point-in-time 500]

Restores the latest database backup into a temporary directory (read-only),
collects every trade the strategies would have taken with their own exits and
the live entry filters replayed on each signal day, and runs them through
backend/app/engine/portfolio_bt.run_portfolio(). Writes stats, yearly returns,
per-strategy results and every fill to OUT.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("GTF_DATA_DIR", tempfile.mkdtemp(prefix="portfolio-bt-"))
os.environ.setdefault("DB_BACKUP_REPO", "kkute2118-hash/Backtesting-")
os.environ.setdefault("DB_BACKUP_BRANCH", "db-backup")

from app.engine import core  # noqa: E402
from app.engine import portfolio_bt as pb  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--slots", type=int, default=10)
    ap.add_argument("--risk", type=float, default=1.0, help="%% of capital risked per trade")
    ap.add_argument("--strategies", default="S4_SEPA,S5_POCKETPIVOT,S6_BREAKOUT")
    ap.add_argument("--buckets", default="", help="STRAT=weight,...; empty = one shared pool")
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--no-costs", action="store_true")
    ap.add_argument("--point-in-time", type=int, default=0,
                    help="restrict to the point-in-time top N by traded value (0 = off)")
    args = ap.parse_args()

    core.restore_db_from_github(force=True)
    core._persist_raw_fingerprints = lambda *a, **k: None      # research run: write nothing back
    con = core._db()
    try:
        syms = [r[0] for r in con.execute(
            "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' GROUP BY symbol HAVING COUNT(*) >= 260")]
    finally:
        con.close()
    data = core.load_scan_dataset(syms, lookback_days=2600)
    end = args.end or str(core.last_expected_nse_session())
    strategies = tuple(s.strip() for s in args.strategies.split(",") if s.strip())
    eligible = core.point_in_time_universe(data, top_n=args.point_in_time) if args.point_in_time else None
    trades = pb.collect_trades(data, args.start, end, strategies=strategies, eligible=eligible)
    buckets = ({k: float(v) for k, v in (p.split("=") for p in args.buckets.split(",") if p)}
               if args.buckets else None)
    res = pb.run_portfolio(trades, pb.close_matrix(data), capital=args.capital, buckets=buckets,
                           risk_pct=args.risk, max_positions=args.slots,
                           costs=pb.NO_COSTS if args.no_costs else pb.IndianDeliveryCosts(),
                           start=args.start, end=end)
    fills = res.fills.copy()
    for c in fills.columns:
        if str(fills[c].dtype).startswith("datetime"):
            fills[c] = fills[c].astype(str)
    out = {"stats": res.stats, "equity": {str(k.date()): round(float(v), 2) for k, v in res.equity.items()},
           "fills": json.loads(fills.to_json(orient="records", date_format="iso"))}
    Path(args.out).write_text(json.dumps(out, indent=1, default=str))
    s = res.stats
    print(f"{args.capital:,.0f} -> {s['final']:,.0f}  CAGR {s['cagr_pct']}%  max drawdown {s['max_drawdown_pct']}%  "
          f"trades {s['trades']}  win {s['win_pct']}%  costs {s['costs']:,.0f}")


if __name__ == "__main__":
    main()
