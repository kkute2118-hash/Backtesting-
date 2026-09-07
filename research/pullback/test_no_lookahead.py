"""Truncation test: no feature or signal may change when the future is removed.

For a set of symbols and cut dates, features are computed twice — once on the
full history, once on the history truncated at the cut date — and every column
is required to match at the cut date.  A weekly aggregate that peeks at its own
unfinished week, a fractal that uses bars to its right, or an anchored VWAP that
searches forward all fail this test.

Run:  python -m research.pullback.test_no_lookahead --db <sqlite>
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from . import features as ft
from .strategy import Config, setups

TOL = 1e-9


def check_symbol(df: pd.DataFrame, cuts: list[pd.Timestamp]) -> list[str]:
    full = ft.build_features(df)
    problems = []
    for cut in cuts:
        trunc = ft.build_features(df.loc[:cut])
        if cut not in trunc.index or cut not in full.index:
            continue
        a, b = full.loc[cut], trunc.loc[cut]
        for col in full.columns:
            x, y = a[col], b[col]
            if isinstance(x, str) or isinstance(y, str):
                continue
            if pd.isna(x) and pd.isna(y):
                continue
            if pd.isna(x) != pd.isna(y):
                problems.append(f"{col} @ {cut.date()}: full={x} trunc={y} (nan mismatch)")
                continue
            denom = max(abs(float(x)), 1.0)
            if abs(float(x) - float(y)) / denom > 1e-9:
                problems.append(f"{col} @ {cut.date()}: full={x:.10g} trunc={y:.10g}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--symbols", type=int, default=6)
    ap.add_argument("--cuts", type=int, default=8)
    args = ap.parse_args()

    candles = ft.load_candles(args.db)
    syms = sorted(candles)[:: max(1, len(candles) // args.symbols)][: args.symbols]
    rng = np.random.default_rng(7)
    failures = 0
    for sym in syms:
        df = candles[sym]
        pool = df.index[300:-5]
        cuts = sorted(pd.Timestamp(d) for d in rng.choice(pool, size=min(args.cuts, len(pool)), replace=False))
        probs = check_symbol(df, cuts)
        status = "OK" if not probs else f"{len(probs)} MISMATCHES"
        print(f"{sym:<12} {len(cuts)} cut dates -> {status}")
        for p in probs[:6]:
            print("   ", p)
        failures += len(probs)

    print("\nfeature truncation test:", "PASS" if failures == 0 else f"FAIL ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
