"""Rank inside a universe you can actually buy.

Two things had to be corrected before going further.

The apparent inversion in the last two years was largely an artefact of
pooling quarters. Cutting deciles across the whole period mixes quarters
whose baseline R differs by several multiples, so the deciles partly sort
quarters rather than trades. Measured WITHIN each quarter, the top-minus-
bottom spread over the last eight quarters averages +0.12 R - weakly
positive, not inverted.

And the single best-ranking feature in every period is "least liquid", which
is the capacity trap already identified and removed in round two: the
illiquid tail cannot absorb real money, and its backtest returns are an
artefact of trading names you could not trade. So the floor goes on FIRST,
and everything is re-measured inside the universe that survives it.
"""
import numpy as np, pandas as pd
pd.set_option("display.width", 250)
CUT = pd.Timestamp("2024-09-04")

W = pd.read_parquet("/tmp/gtf/pool_scored.parquet")
W["date"] = pd.to_datetime(W["date"])
W["q"] = W.date.dt.to_period("Q")

print("=" * 104)
print("1. WHAT THE LIQUIDITY FLOOR COSTS, AND WHAT IT REMOVES")
print("=" * 104)
rows = []
for flo in (0, 5, 10, 25, 50, 100):
    g = W[W.turnover_cr >= flo]
    g2 = g[g.date >= CUT]
    rows.append({"turnover floor (Cr)": flo, "candidates": len(g),
                 "share kept": f"{100*len(g)/len(W):.0f}%",
                 "symbols": g.symbol.nunique(),
                 "avgR full": round(g.R.mean(), 3),
                 "avgR last 2y": round(g2.R.mean(), 3),
                 "avg% last 2y": round(g2.p.mean(), 2)})
print(pd.DataFrame(rows).to_string(index=False))

FLOOR = 25
V = W[W.turnover_cr >= FLOOR].copy()
print(f"\nusing a {FLOOR} Cr floor: {len(V)} candidates, {V.symbol.nunique()} symbols")

print("\n" + "=" * 104)
print(f"2. SIMPLE RANKERS INSIDE THE TRADEABLE UNIVERSE (top 2% by each, avg R)")
print("=" * 104)
early = V[V.date < "2024-01-01"]; late = V[V.date >= "2024-01-01"]; last2 = V[V.date >= CUT]
rows = []
for f, sign, lab in (("pred", 1, "the walk-forward model"),
                     ("src_score", 1, "source's own score"),
                     ("ret_120d", -1, "weakest 6-month momentum"),
                     ("ret_120d", 1, "strongest 6-month momentum"),
                     ("ret_20d", -1, "weakest 1-month"),
                     ("dist_ema200_atr", -1, "furthest below 200 EMA"),
                     ("pct_from_52w_high", -1, "furthest below 52w high"),
                     ("atr_pct", -1, "calmest"),
                     ("rsi14", -1, "most oversold"),
                     ("w_slope", 1, "strongest weekly trend"),
                     ("m_slope", 1, "strongest monthly trend"),
                     ("n_sources", 1, "flagged by most sources"),
                     ("vol20d", -1, "lowest realised vol")):
    r = {"rank by": lab}
    for nm, g in (("full", V), ("2022-23", early), ("2024+", late), ("last 2y", last2)):
        v = (g[f] * sign).to_numpy()
        k = max(int(len(g) * 0.02), 40)
        r[nm] = round(float(g.R.iloc[np.argsort(-v)[:k]].mean()), 3)
    rows.append(r)
t = pd.DataFrame(rows)
print(t.to_string(index=False))
print(f"\nbaseline R in this universe: full {V.R.mean():+.3f}  2022-23 {early.R.mean():+.3f}  "
      f"2024+ {late.R.mean():+.3f}  last 2y {last2.R.mean():+.3f}")

print("\n" + "=" * 104)
print("3. WITHIN-QUARTER RANKING POWER OF THE MODEL, INSIDE THE FLOOR")
print("=" * 104)
rows = []
for per, g in V.groupby("q"):
    if len(g) < 1500: continue
    dec = pd.qcut(g.pred, 5, labels=False, duplicates="drop")
    rows.append({"quarter": str(per), "n": len(g),
                 "top fifth R": round(g.R[dec == dec.max()].mean(), 3),
                 "bottom fifth R": round(g.R[dec == 0].mean(), 3),
                 "spread": round(g.R[dec == dec.max()].mean() - g.R[dec == 0].mean(), 3),
                 "all R": round(g.R.mean(), 3)})
q = pd.DataFrame(rows)
print(q.to_string(index=False))
print(f"\nmean spread, all quarters: {q.spread.mean():+.3f} R"
      f"   positive in {int((q.spread>0).sum())}/{len(q)} quarters")
rec = q[q.quarter >= "2024Q3"]
print(f"mean spread, last 2 years:  {rec.spread.mean():+.3f} R"
      f"   positive in {int((rec.spread>0).sum())}/{len(rec)} quarters")
