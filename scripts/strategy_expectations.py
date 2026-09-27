#!/usr/bin/env python3
"""Write research/strategy_expectations.json: what each strategy's trades
looked like in the backtest, for the dashboard's live-vs-backtest check.

    python scripts/strategy_expectations.py [--start 2022-01-01]

Trades come from backend/app/engine/portfolio_bt.collect_trades(): the
engine's own replays with the live entry filter and the data guard replayed
on each signal day. Returns are gross (exit / entry - 1), the same measure the
forward tracker records. Read-only with respect to the database backup.
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
os.environ.setdefault("GTF_DATA_DIR", tempfile.mkdtemp(prefix="expectations-"))
os.environ.setdefault("DB_BACKUP_REPO", "kkute2118-hash/Backtesting-")
os.environ.setdefault("DB_BACKUP_BRANCH", "db-backup")

from app.engine import core  # noqa: E402
from app.engine import portfolio_bt as pb  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--out", default=str(ROOT / "research" / "strategy_expectations.json"))
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
    trades = pb.collect_trades(data, args.start, end)
    trades = trades[trades.exit_reason.astype(str).str.upper() != "OPEN"]
    trades["ret"] = (trades.exit / trades.entry - 1) * 100
    trades["r"] = (trades.exit - trades.entry) / (trades.entry - trades.stop)
    out = {"generated_from": f"engine replay {args.start} to {end}, closed trades only",
           "strategies": {}}
    for s, g in trades.groupby("strategy"):
        out["strategies"][s] = {
            "trades": int(len(g)),
            "win_pct": round(float((g.ret > 0).mean() * 100), 1),
            "avg_return_pct": round(float(g.ret.mean()), 2),
            "median_return_pct": round(float(g.ret.median()), 2),
            "avg_r": round(float(g.r.mean()), 3),
            "avg_holding_days": round(float((g.exit_date - g.entry_date).dt.days.mean()), 1),
        }
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
