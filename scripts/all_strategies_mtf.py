#!/usr/bin/env python3
"""₹1 lakh through every strategy, S1-S6, with and without margin (MTF).

    python scripts/all_strategies_mtf.py OUT.json [--start 2022-01-01] [--leverage 1,2,4]

Each strategy alone, and the scanner's current S4+S5+S6 in one shared pool,
through backend/app/engine/portfolio_bt.run_portfolio(): 10 slots, 1% risk
per trade (scaled by leverage), Indian delivery costs, and for MTF 12.5% a
year interest on the borrowed amount plus ₹20 pledge per buy. Trades come
from collect_trades(): each strategy's own exits, its live entry filter and
the data guard replayed on the signal day. Read-only with respect to the
database backup.
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
os.environ.setdefault("GTF_DATA_DIR", tempfile.mkdtemp(prefix="all-mtf-"))
os.environ.setdefault("DB_BACKUP_REPO", "kkute2118-hash/Backtesting-")
os.environ.setdefault("DB_BACKUP_BRANCH", "db-backup")

from app.engine import core  # noqa: E402
from app.engine import portfolio_bt as pb  # noqa: E402

ALL = ("S1", "S2", "S3", "S4_SEPA", "S5_POCKETPIVOT", "S6_BREAKOUT")
BOOKS = {s: (s,) for s in ALL} | {"S4+S5+S6 (scanner today)": ("S4_SEPA", "S5_POCKETPIVOT", "S6_BREAKOUT")}
KEEP = ("final", "cagr_pct", "max_drawdown_pct", "trades", "win_pct", "costs", "interest_paid",
        "yearly_return_pct")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--leverage", default="1,2,4")
    args = ap.parse_args()
    levels = [float(x) for x in args.leverage.split(",")]

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
    trades = pb.collect_trades(data, args.start, end, strategies=ALL)
    closes = pb.close_matrix(data)
    print({s: int((trades.strategy == s).sum()) for s in ALL}, flush=True)

    out = {"window": f"{args.start} to {end}", "capital": 100_000,
           "assumptions": "10 slots, 1% risk x leverage, 25% cap x leverage, Indian delivery costs, "
                          "MTF 12.5%/yr interest + Rs 20 pledge per buy, margin calls not modelled",
           "books": {}}
    for name, strats in BOOKS.items():
        t = trades[trades.strategy.isin(strats)]
        out["books"][name] = {}
        for lev in levels:
            r = pb.run_portfolio(t, closes, capital=100_000, max_positions=10, risk_pct=1.0,
                                 costs=pb.IndianDeliveryCosts(), start=args.start, end=end,
                                 leverage=lev)
            row = {k: r.stats.get(k) for k in KEEP}
            out["books"][name][f"{lev:g}x"] = row
            print(f"{name:28s} {lev:g}x  final {row['final']:>12,.0f}  CAGR {row['cagr_pct']:>6}%  "
                  f"maxDD {row['max_drawdown_pct']:>7}%  trades {row['trades']:>4}  win {row['win_pct']}%  "
                  f"interest {row['interest_paid']:,.0f}", flush=True)
    Path(args.out).write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
