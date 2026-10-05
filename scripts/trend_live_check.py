#!/usr/bin/env python3
"""Replay the live trend paper book (app.tasks.trend_paper) bar by bar over the
real 2021-2026 history and print its trades by market and period, to check it
matches the strategy search (scripts/search_trend_grid.py, step 14).

Spot gold (XAUUSD) stands in for XAUUSDT. The live book charges perpetual fees
on gold; the grid charged the recorded spot spread, so gold differs slightly.

Usage: python scripts/trend_live_check.py DATA_DIR
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.tasks import trend_paper as tp  # noqa: E402

FILES = {"BTCUSDT": "BTCUSDT", "ETHUSDT": "ETHUSDT", "SOLUSDT": "SOLUSDT", "XAUUSDT": "XAUUSD"}
START = pd.Timestamp("2021-08-01", tz="UTC")
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def main():
    data = Path(sys.argv[1])
    rows = []
    for sym, f in FILES.items():
        df = pd.read_csv(data / f"{f}_5m.csv.gz", usecols=["time", "open", "high", "low", "close"])
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time").sort_index()
        d1, h4, m15 = tp._resample(df, "1D"), tp._resample(df, "4h"), tp._resample(df, "15min")
        st = {"last15": str(m15.index[m15.index < START][-1]), "status": "flat"}
        tp.advance(st, tp.indicators(d1, h4), m15, sym)
        rows += st.get("closed", [])
    t = pd.DataFrame(rows)
    t["period"] = (pd.to_datetime(t.exit_time, utc=True) >= SPLIT).map({False: "2021-24", True: "2025-26"})
    out = t.groupby(["symbol", "period"]).r.agg(trades="size", avg_r="mean", total_r="sum").round(2)
    print(out.to_string())
    print(t.groupby("period").r.agg(trades="size", avg_r="mean").round(2).to_string())


if __name__ == "__main__":
    main()
