#!/usr/bin/env python3
"""Swing mode of the liquidity framework (4h regime, 1h setups, 15m entries)
on gold and crypto, all paying crypto-exchange perpetual fees (gold as
XAU/USDT, history from Dukascopy spot). Variants: entry (limit / LTF micro
MSB) and fees (taker / maker).

Usage: python scripts/liquidity_swing_runs.py DATA_DIR OUT.csv
"""
import ast
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.engine import liquidity_pa as lp  # noqa: E402

SYMBOLS = ("XAUUSD", "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
TAKER = 0.0005 * 1.18 + 0.0001      # per side: taker fee + 18% GST + slippage
MAKER = 0.0002 * 1.18 + 0.0001      # limit entry and target as maker; stops still slip
SWING = dict(htf="4h", mtf="1h", ltf="15min", max_hold=192, retest_bars=24, msb_bars=16,
             ltf_confirm_bars=16, fast_leg=8, pool_max_age=24 * 20, fill_through=0.05, fee_mode="perp")


def main():
    data, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows = []
    for sym in SYMBOLS:
        df = pd.read_csv(data / f"{sym}_5m.csv.gz")
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time").sort_index()
        for entry in ("limit", "ltf"):
            for fee_name, fee in (("taker", TAKER), ("maker", MAKER)):
                if entry == "ltf" and fee_name == "maker":
                    continue                     # an LTF entry is a market order
                p = lp.Params(entry=entry, crypto_cost_per_side=fee, **SWING)
                r = lp.backtest(df, sym, p)
                r = r[r.decision == "TRADE"].copy()
                r["entry_mode"], r["fees"] = entry, fee_name
                rows.append(r)
                print(f"{sym} {entry} {fee_name}: {len(r)} trades", file=sys.stderr, flush=True)
    allr = pd.concat(rows, ignore_index=True)
    ex = pd.json_normalize(allr.pop("extras").map(lambda e: e if isinstance(e, dict) else ast.literal_eval(e)))
    pd.concat([allr.reset_index(drop=True), ex], axis=1).to_csv(out, index=False)


if __name__ == "__main__":
    main()
