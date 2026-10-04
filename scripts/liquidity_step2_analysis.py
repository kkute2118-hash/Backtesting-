#!/usr/bin/env python3
"""Step 2 analysis on the output of liquidity_step2_runs.py: candidate rules
chosen on 2021-24, checked on 2025-26, with a Rs 10,000 account and a spread
sensitivity check. Usage: python scripts/liquidity_step2_analysis.py TRADES.csv
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.engine.liquidity_pa import metrics  # noqa: E402

SESSION_UTC = {6, 7, 12, 13, 14, 15}          # London open, New York morning


def strategy(t, min_score=0):
    m = ((~t.symbol.str.endswith("USDT")) & (t.entry_mode == "limit") & (t.family == "continuation")
         & t.hour_utc.isin(SESSION_UTC) & (t.score >= min_score))
    return t[m].sort_values("ts")


def main():
    t = pd.read_csv(sys.argv[1])
    t["ts"] = pd.to_datetime(t.entry_time, utc=True)
    t["test"] = t.ts.dt.year >= 2025
    for name, g in (("A run->retest, session", strategy(t)), ("B = A with score >= 65", strategy(t, 65))):
        print(f"\n{name}\n 2021-24 {metrics(g[~g.test].r)}\n 2025-26 {metrics(g[g.test].r)}")
        for k in (1, 2, 3, 5):
            r = g.r - (k - 1) * g.cost_r
            print(f"  spread x{k}: {r[~g.test].mean():+.3f}R / {r[g.test].mean():+.3f}R")
        for risk in (0.005, 0.01):
            eq = peak = 10_000.0
            mdd = 0.0
            for x in g.r:
                eq *= 1 + risk * x
                peak = max(peak, eq)
                mdd = min(mdd, eq / peak - 1)
            print(f"  Rs10,000 at {risk:.1%} risk: Rs{eq:,.0f}, worst drawdown {mdd:.0%}")


if __name__ == "__main__":
    main()
