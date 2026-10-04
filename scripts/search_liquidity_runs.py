#!/usr/bin/env python3
"""Every traded setup of the liquidity framework (app.engine.liquidity_pa) under
16 engine variants: intraday (1h/15m/5m) or swing (4h/1h/15m) timeframes,
limit or LTF-confirmation entry, minimum R:R 1.5 or 2, stop buffer 0.10 or
0.25 ATR. Limits fill only 0.05 ATR through (research STEP3). Crypto pays
taker fee + 18% GST + slippage per side and funding; forex and gold pay their
recorded spread. Filters on the recorded features are searched afterwards by
scripts/search_strategies.py.

Usage: python scripts/search_liquidity_runs.py DATA_DIR OUT.csv.gz SYMBOL [SYMBOL ...]
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.engine import liquidity_pa as lp  # noqa: E402

TAKER = 0.0005 * 1.18 + 0.0001
SWING = dict(htf="4h", mtf="1h", ltf="15min", max_hold=192, retest_bars=24, msb_bars=16,
             ltf_confirm_bars=16, fast_leg=8, pool_max_age=24 * 20)
KEEP = ["symbol", "family", "direction", "event", "pool_kind", "htf_regime", "htf_aligned", "msb",
        "displacement", "fvg", "zone", "discount_ok", "ote", "entry_time", "exit_time", "rr1",
        "score", "r", "cost_r", "hold_minutes"]


def main():
    data, out, symbols = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
    rows = []
    for sym in symbols:
        df = pd.read_csv(data / f"{sym}_5m.csv.gz")
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time").sort_index()
        for mode, entry, min_rr, buf in itertools.product(("intraday", "swing"), ("limit", "ltf"),
                                                          (1.5, 2.0), (0.10, 0.25)):
            extra = SWING if mode == "swing" else {}
            p = lp.Params(entry=entry, min_rr=min_rr, stop_buffer=buf, fill_through=0.05,
                          crypto_cost_per_side=TAKER, **extra)
            r = lp.backtest(df, sym, p)
            r = r[r.decision == "TRADE"][KEEP].copy()
            r["variant"] = f"{mode}|{entry}|rr{min_rr}|buf{buf}"
            rows.append(r)
            print(f"{sym} {r['variant'].iat[0] if len(r) else mode}: {len(r)} trades", file=sys.stderr, flush=True)
        del df
    pd.concat(rows, ignore_index=True).to_csv(out, index=False)


if __name__ == "__main__":
    main()
