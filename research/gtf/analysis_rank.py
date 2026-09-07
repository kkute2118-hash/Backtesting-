"""Does ranking actually pick better trades? And what does 2-3 a week return?"""
import numpy as np, pandas as pd, sqlite3, time
import rank as RK
pd.set_option("display.width", 250)
DB = ("/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c"
      "/scratchpad/data/market_data.sqlite3")
CUT = pd.Timestamp("2024-09-04")

t0 = time.time()
d = RK.prepare()
d, fitted = RK.walkforward(d)
print(f"{len(fitted)} quarters scored out of sample: {fitted[0]} .. {fitted[-1]}"
      f"  ({time.time()-t0:.0f}s)")
W = d[d.pred.notna()].copy()
print(f"scored window: {W.date.min().date()} .. {W.date.max().date()}   {len(W)} candidates\n")
W.to_parquet("/tmp/gtf/pool_scored.parquet", index=False)

print("=" * 108)
print("1. IS THE RANKING INFORMATIVE AT ALL? out-of-sample decile of predicted R")
print("=" * 108)
W["dec"] = W.groupby("q")["pred"].transform(
    lambda s: pd.qcut(s, 10, labels=False, duplicates="drop"))
t = W.groupby("dec").agg(n=("R", "size"), avgR=("R", "mean"), avg_pct=("p", "mean"),
                         win=("p", lambda s: 100 * (s > 0).mean()))
print(t.round(3).to_string())
print(f"\nspread top decile minus bottom: {t.avgR.iloc[-1] - t.avgR.iloc[0]:+.3f} R")

print("\n" + "=" * 108)
print("2. THE SAME, LAST 2 YEARS ONLY")
print("=" * 108)
L = W[W.date >= CUT].copy()
L["dec"] = pd.qcut(L.pred, 10, labels=False, duplicates="drop")
t2 = L.groupby("dec").agg(n=("R", "size"), avgR=("R", "mean"), avg_pct=("p", "mean"),
                          win=("p", lambda s: 100 * (s > 0).mean()))
print(t2.round(3).to_string())
print(f"\nspread top decile minus bottom: {t2.avgR.iloc[-1] - t2.avgR.iloc[0]:+.3f} R")

print("\n" + "=" * 108)
print("3. WHAT THE WEEKLY BUDGET ACTUALLY SELECTS")
print("=" * 108)
rows = []
for thr in ("thr90", "thr95", "thr97.5", "thr99", "thr99.5"):
    for pw in (2, 3):
        s = RK.weekly_pick(W, thr, per_week=pw)
        wk = s.date.dt.to_period("W").nunique()
        s2 = s[s.date >= CUT]
        rows.append({"threshold": thr, "per week": pw, "trades": len(s),
                     "weeks active": wk,
                     "trades/wk": round(len(s) / max(wk, 1), 2),
                     "avgR": round(s.R.mean(), 3), "avg%": round(s.p.mean(), 2),
                     "win%": round(100 * (s.p > 0).mean(), 1),
                     "last2y n": len(s2), "last2y avgR": round(s2.R.mean(), 3),
                     "last2y avg%": round(s2.p.mean(), 2)})
print(pd.DataFrame(rows).to_string(index=False))
print(f"\nfor reference, the whole pool averages {W.R.mean():+.3f} R "
      f"({W.p.mean():+.2f}%), and in the last 2 years "
      f"{W[W.date>=CUT].R.mean():+.3f} R ({W[W.date>=CUT].p.mean():+.2f}%)")

print("\n" + "=" * 108)
print("4. WHERE DO THE PICKS COME FROM?")
print("=" * 108)
s = RK.weekly_pick(W, "thr99", per_week=3)
print(pd.crosstab(s.source, s.date.dt.year).to_string())
print("\naverage R by source among the picks:")
print(s.groupby("source")["R"].agg(["size", "mean"]).round(3).to_string())
