#!/usr/bin/env python3
"""S1-S3 with S6's traits (breadth >= 0.50, >= 60% above the 52-week low,
within 15% of the 52-week high) through the Rs 1 lakh account, against S4-S6.

    python scripts/s123_account.py OUT.json

Same account as research/STRATEGY_SHORTLIST.md: one pool, 10 slots, 1% risk,
Indian delivery costs, one position per stock. Read-only with respect to the
database backup.
"""
from __future__ import annotations

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
os.environ.setdefault("GTF_DATA_DIR", tempfile.mkdtemp(prefix="s123acct-"))
os.environ.setdefault("DB_BACKUP_REPO", "kkute2118-hash/Backtesting-")
os.environ.setdefault("DB_BACKUP_BRANCH", "db-backup")

from app.engine import core  # noqa: E402
from app.engine import portfolio_bt as pb  # noqa: E402

START = "2022-01-01"


def main():
    out_path = Path(sys.argv[1])
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
    gate = {}
    for k, df in data.items():
        if df is None or len(df) < 260:
            continue
        f = core.strategy6_features(core.attach_market_breadth(df, breadth))
        gate[str(k).replace(".NS", "")] = ((f.s6_breadth >= core.S6_MIN_BREADTH)
                                           & (f.s6_above_52w_low_pct >= core.S6_MIN_ABOVE_52W_LOW_PCT)
                                           & (f.s6_below_52w_high_pct <= core.S6_MAX_BELOW_52W_HIGH_PCT))

    old = pb.collect_trades(data, START, end, strategies=("S1", "S2", "S3"), apply_entry_filter=False)
    keep = [bool(gate.get(s, pd.Series(dtype=bool)).get(pd.Timestamp(d), False))
            for s, d in zip(old.symbol, old.signal_date)]
    better = old[keep].copy()
    better["strategy"] = better.strategy + "+S6traits"
    live = pb.collect_trades(data, START, end)                  # S4, S5, S6 as they run
    closes = pb.close_matrix(data)

    def acct(t):
        r = pb.run_portfolio(t, closes, capital=100_000, max_positions=10, risk_pct=1.0,
                             costs=pb.IndianDeliveryCosts(), start=START, end=end,
                             priority=tuple(sorted(t.strategy.unique())))
        s = r.stats
        return {k: s[k] for k in ("final", "cagr_pct", "max_drawdown_pct", "trades", "win_pct", "yearly_return_pct")}

    books = {}
    for s in ("S1", "S2", "S3"):
        books[f"{s} as it was"] = old[old.strategy == s]
        books[f"{s} + S6 traits"] = better[better.strategy == f"{s}+S6traits"]
    books["S1+S2+S3 + S6 traits"] = better
    books["S6 alone"] = live[live.strategy == "S6_BREAKOUT"]
    books["S4+S5+S6 (today)"] = live
    books["S4+S5+S6 + improved S1-S3"] = pd.concat([live, better])
    out = {}
    for name, t in books.items():
        out[name] = acct(t)
        print(f"{name:32s} {json.dumps(out[name])}", flush=True)
    out_path.write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
