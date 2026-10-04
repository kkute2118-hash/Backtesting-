#!/usr/bin/env python3
"""Step 2 runs: every symbol with limit and LTF entries; crypto under taker
and maker fee assumptions. Writes one CSV of every traded setup with its
features (extras expanded) for scripts/liquidity_step2_analysis.py.

Usage: python scripts/liquidity_step2_runs.py DATA_DIR OUT.csv
"""
import ast
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.engine import liquidity_pa as lp  # noqa: E402

# Per side, as a fraction of price. Indian crypto exchanges charge 18% GST on fees.
TAKER = 0.0005 * 1.18 + 0.0001      # taker fee + GST + slippage
MAKER = 0.0002 * 1.18 + 0.0001      # limit entries and targets as maker; stops still slip


def main():
    data, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows = []
    for f in sorted(data.glob("*_5m.csv.gz")):
        sym = f.name.split("_5m")[0]
        df = pd.read_csv(f)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time").sort_index()
        fees = {"taker": TAKER, "maker": MAKER} if lp.is_crypto(sym) else {"spread": 0.0}
        for entry in ("limit", "ltf"):
            for fee_name, fee in fees.items():
                if entry == "ltf" and fee_name == "maker":
                    continue                     # an LTF entry is a market order
                p = lp.Params(entry=entry, crypto_cost_per_side=fee or lp.CRYPTO_COST_PER_SIDE)
                r = lp.backtest(df, sym, p)
                r = r[r.decision == "TRADE"].copy()
                r["entry_mode"], r["fees"] = entry, fee_name
                rows.append(r)
                print(f"{sym} {entry} {fee_name}: {len(r)} trades", file=sys.stderr, flush=True)
    allr = pd.concat(rows, ignore_index=True)
    ex = pd.json_normalize(allr.pop("extras").map(lambda e: e if isinstance(e, dict) else ast.literal_eval(e)))
    allr = pd.concat([allr.reset_index(drop=True), ex], axis=1)
    allr.to_csv(out, index=False)


if __name__ == "__main__":
    main()
