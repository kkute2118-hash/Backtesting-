#!/usr/bin/env python3
"""Backtest the owner's liquidity + price action framework
(backend/app/engine/liquidity_pa.py) on the stored 5-minute history and
measure what each concept adds (framework section 29), separately for
2021-24 (rules may be chosen here) and 2025-26 (they must hold here).

Usage: python scripts/liquidity_pa_study.py DATA_DIR OUT_DIR [--symbols A,B] [--entry ltf|limit]
Writes OUT_DIR/trades_<entry>.csv (every setup, section 28 fields) and
OUT_DIR/summary_<entry>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.engine import liquidity_pa as lp  # noqa: E402

SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def load(path):
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


def breakdown(tr: pd.DataFrame) -> dict:
    out = {"all": lp.metrics(tr.r)}
    cols = ["symbol", "family", "event", "msb", "displacement", "fvg", "zone", "htf_aligned",
            "discount_ok", "ote", "pool_kind", "grade", "direction"]
    for col in cols:
        out[col] = {str(k): lp.metrics(g.r) for k, g in tr.groupby(col)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--entry", default="ltf")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    want = {s for s in a.symbols.split(",") if s}
    frames = []
    for f in sorted(Path(a.data).glob("*_5m.csv.gz")):
        sym = f.name.split("_5m")[0]
        if want and sym not in want:
            continue
        t = time.time()
        r = lp.backtest(load(f), sym, lp.Params(entry=a.entry))
        frames.append(r)
        n = int((r.decision == "TRADE").sum()) if len(r) else 0
        print(f"{sym}: {len(r)} setups, {n} trades ({time.time() - t:.0f}s)", file=sys.stderr, flush=True)
    allr = pd.concat(frames, ignore_index=True)
    allr.to_csv(out / f"trades_{a.entry}.csv", index=False)
    tr = allr[allr.decision == "TRADE"].copy()
    tr["grade"] = tr.extras.map(lambda e: e.get("grade") if isinstance(e, dict) else None)
    tr["t"] = pd.to_datetime(tr.entry_time, utc=True)
    tr = tr.sort_values("t")
    summary = {"setups": int(len(allr)),
               "rejected": allr[allr.decision != "TRADE"].reject_reason.value_counts().to_dict(),
               "2021-24": breakdown(tr[tr.t < SPLIT]),
               "2025-26": breakdown(tr[tr.t >= SPLIT])}
    (out / f"summary_{a.entry}.json").write_text(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
