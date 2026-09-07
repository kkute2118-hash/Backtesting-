"""The ranking inverted. Find out when, why, and whether anything survives.

The walk-forward model ranks well over the full window (+0.204 R top decile
minus bottom) and ranks BACKWARDS over the last two years (-0.293 R). A model
whose confident picks are its worst trades is worse than no model, so nothing
gets built on top of it until this is understood.
"""
import numpy as np, pandas as pd
import rank as RK
pd.set_option("display.width", 250)
CUT = pd.Timestamp("2024-09-04")

W = pd.read_parquet("/tmp/gtf/pool_scored.parquet")
W["date"] = pd.to_datetime(W["date"])
W["q"] = W.date.dt.to_period("Q")

print("=" * 100)
print("1. WHEN DID IT INVERT? top-decile minus bottom-decile R, by half-year")
print("=" * 100)
rows = []
for per, g in W.groupby(W.date.dt.to_period("2Q" if False else "Q")):
    if len(g) < 2000: continue
    dec = pd.qcut(g.pred, 10, labels=False, duplicates="drop")
    top = g.R[dec == dec.max()]; bot = g.R[dec == 0]
    rows.append({"quarter": str(per), "n": len(g),
                 "top decile R": round(top.mean(), 3),
                 "bottom decile R": round(bot.mean(), 3),
                 "spread": round(top.mean() - bot.mean(), 3),
                 "all R": round(g.R.mean(), 3)})
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 100)
print("2. WHAT IS THE MODEL LEANING ON? feature means, top vs bottom decile")
print("=" * 100)
W["dec"] = W.groupby("q")["pred"].transform(
    lambda s: pd.qcut(s, 10, labels=False, duplicates="drop"))
cols = ["ret_120d", "ret_60d", "ret_20d", "dist_ema200_atr", "pct_from_52w_high",
        "atr_pct", "turnover_cr", "rsi14", "w_slope", "m_slope", "src_score"]
t = W.groupby("dec")[cols].mean()
print(t.round(2).to_string())

print("\n" + "=" * 100)
print("3. SIMPLE RANKERS, no model. Does anything rank in BOTH periods?")
print("   reported as: average R of the top 1% by that feature")
print("=" * 100)
rows = []
early = W[W.date < "2024-01-01"]; late = W[W.date >= "2024-01-01"]
last2 = W[W.date >= CUT]
for f, sign, lab in (("pred", 1, "the model"),
                     ("src_score", 1, "source's own score"),
                     ("turnover_cr", 1, "most liquid"),
                     ("turnover_cr", -1, "least liquid"),
                     ("ret_120d", 1, "strongest 6-month momentum"),
                     ("ret_120d", -1, "weakest 6-month momentum"),
                     ("dist_ema200_atr", -1, "furthest below 200 EMA"),
                     ("dist_ema200_atr", 1, "furthest above 200 EMA"),
                     ("pct_from_52w_high", 1, "closest to 52w high"),
                     ("atr_pct", -1, "calmest"),
                     ("atr_pct", 1, "most volatile"),
                     ("rsi14", -1, "most oversold"),
                     ("w_slope", 1, "strongest weekly trend"),
                     ("n_sources", 1, "flagged by most sources")):
    r = {"rank by": lab}
    for nm, g in (("full", W), ("2022-2023", early), ("2024+", late), ("last 2y", last2)):
        v = g[f] * sign
        k = max(int(len(g) * 0.01), 50)
        top = g.R.iloc[np.argsort(-v.to_numpy())[:k]]
        r[nm] = round(float(top.mean()), 3)
    r["all candidates"] = round(float(W.R.mean()), 3)
    rows.append(r)
print(pd.DataFrame(rows).to_string(index=False))
print(f"\npool baseline R: full {W.R.mean():+.3f}   2022-2023 {early.R.mean():+.3f}   "
      f"2024+ {late.R.mean():+.3f}   last 2y {last2.R.mean():+.3f}")
