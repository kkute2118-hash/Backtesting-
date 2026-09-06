"""Matched placebo for every liquidity setup, plus the same-bar mirror trade.

Two controls, because they answer different questions.

  placebo  same symbol, same calendar month, same side, same stop distance in
           percent, random bar. Holds regime and geometry fixed and removes
           only the pattern. Anything the setup earns above this is what the
           liquidity read is worth, as opposed to what the market did.

  mirror   the same bar, same stop distance, opposite direction. This is the
           direct test of the transcript's central claim - that the grab and
           sweep are REVERSAL signals while the run is a CONTINUATION signal.
           If the classifier carries no directional information, a setup and
           its mirror are just two sides of a coin.
"""
import argparse, sqlite3, time
import numpy as np, pandas as pd
import gtfcore as G
import liq as Q
from build_events import load

ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True)
ap.add_argument("--setups", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--seed", type=int, default=20260906)
ap.add_argument("--hold", type=int, default=60)
ap.add_argument("--reps", type=int, default=5)
a = ap.parse_args()

d = pd.read_parquet(a.setups); d["date"] = pd.to_datetime(d["date"])
rng = np.random.default_rng(a.seed)
rows = []
t0 = time.time()
for si, (sym, grp) in enumerate(d.groupby("symbol", sort=True)):
    df = load(a.db, sym)
    n = len(df)
    O = df["open"].to_numpy(); H = df["high"].to_numpy()
    L = df["low"].to_numpy(); C = df["close"].to_numpy()
    month = np.asarray(df.index.to_period("M"))
    pos = np.arange(n)
    for r in grp.itertuples():
        j = int(r.bar); long = r.side == "long"
        risk = abs(float(r.entry_plan) - float(r.stop_px)) / float(r.entry_plan)
        # mirror: identical bar and risk, opposite direction
        e = float(r.entry_plan)
        mstop = e * (1 + risk) if long else e * (1 - risk)
        p, b, _ = Q.walk(O, H, L, C, j, e, mstop, None, a.hold, not long)
        rows.append({"symbol": sym, "date": r.date, "kind": r.kind,
                     "side": r.side, "what": "mirror", "rep": 0, "p_time": p})
        same = np.nonzero((month == pd.Period(r.date, "M")) & (pos > 0)
                          & (pos + 20 < n))[0]
        # A same-month placebo may enter BEFORE the setup bar, which for a
        # breakout means it collects the very move the setup is trying to
        # trade. That biases the comparison against any momentum pattern, so
        # a forward-only placebo is drawn as well: random bar in the 20
        # trading days AFTER the setup. Neither is perfect; disagreement
        # between them is itself the finding.
        fwd = pos[(pos > j) & (pos <= j + 20) & (pos + 20 < n)]
        for what, pool in (("placebo", same), ("placebo_fwd", fwd)):
            if not len(pool):
                continue
            for rep in range(a.reps):
                k = int(rng.choice(pool))
                e2 = float(C[k])
                s2 = e2 * (1 - risk) if long else e2 * (1 + risk)
                p, b, _ = Q.walk(O, H, L, C, k, e2, s2, None, a.hold, long)
                rows.append({"symbol": sym, "date": r.date, "kind": r.kind,
                             "side": r.side, "what": what, "rep": rep, "p_time": p})
    if (si + 1) % 100 == 0:
        print(f"  {si+1} symbols  {len(rows)} rows  {time.time()-t0:.0f}s", flush=True)

c = pd.DataFrame(rows)
c.to_parquet(a.out, index=False)
print(f"{len(c)} control rows -> {a.out}  ({time.time()-t0:.0f}s)")
