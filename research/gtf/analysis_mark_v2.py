"""Does adding volume and index-position features improve the marking?

Three feature sets, identical walk-forward discipline, compared on the thing
that matters: does the top fifth beat the bottom fifth on win rate, quarter by
quarter, out of sample.
"""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
import rank as RK
pd.set_option("display.width", 250)
CUT = pd.Timestamp("2024-09-04")

d = RK.prepare(); d = d[d.turnover_cr >= 25].copy()
d["win"] = (d.p > 0).astype(int); d["q"] = d.date.dt.to_period("Q")
SRC = [c for c in d.columns if c.startswith("is_")]

SETS = {
    "original": RK.FEATS + SRC,
    "+ volume": RK.FEATS + RK.VOL_FEATS + SRC,
    "+ index position": RK.FEATS + RK.IDX_FEATS + SRC,
    "+ both": RK.FEATS + RK.VOL_FEATS + RK.IDX_FEATS + SRC,
}

for name, feats in SETS.items():
    feats = [f for f in feats if f in d.columns]
    col = f"p_{name}"
    d[col] = np.nan
    for qq in sorted(d.q.unique()):
        past = d[(d.q < qq) & (d.date < qq.start_time - pd.Timedelta(days=RK.RESOLVE_DAYS))]
        if len(past) < RK.MIN_TRAIN:
            continue
        use = [f for f in feats if past[f].notna().sum() > 100 and past[f].nunique() > 1]
        m = HistGradientBoostingClassifier(
            max_depth=3, max_iter=300, learning_rate=0.05, min_samples_leaf=100,
            l2_regularization=1.0, random_state=0).fit(past[use].to_numpy(),
                                                       past.win.to_numpy())
        d.loc[d.q == qq, col] = m.predict_proba(d.loc[d.q == qq, use].to_numpy())[:, 1]
    print(f"fitted {name}: {d[col].notna().sum()} scored", flush=True)

W = d[d[[f"p_{k}" for k in SETS]].notna().all(axis=1)].copy()
W.to_parquet("/tmp/gtf/pool_v2.parquet", index=False)
print(f"\ncomparable window: {W.date.min().date()} .. {W.date.max().date()}, {len(W)} candidates\n")

print("=" * 108)
print("TOP FIFTH MINUS BOTTOM FIFTH, WIN RATE, BY QUARTER")
print("=" * 108)
res = {}
for name in SETS:
    col = f"p_{name}"
    gaps = []
    for per, g in W.groupby("q"):
        if len(g) < 1500: continue
        q5 = pd.qcut(g[col], 5, labels=False, duplicates="drop")
        top, bot = g.p[q5 == q5.max()], g.p[q5 == 0]
        gaps.append({"quarter": str(per),
                     "gap": 100 * ((top > 0).mean() - (bot > 0).mean())})
    res[name] = pd.DataFrame(gaps).set_index("quarter")["gap"]
t = pd.DataFrame(res).round(1)
print(t.to_string())
print("\nsummary:")
rec = t[t.index >= "2024Q3"]
print(pd.DataFrame({
    "mean gap": t.mean().round(2),
    "positive quarters": [f"{int((t[c] > 0).sum())}/{len(t)}" for c in t.columns],
    "mean gap last 2y": rec.mean().round(2),
    "positive last 2y": [f"{int((rec[c] > 0).sum())}/{len(rec)}" for c in rec.columns],
}).to_string())

print("\n" + "=" * 108)
print("TOP-FIFTH QUALITY (the band the weekly picks come from)")
print("=" * 108)
rows = []
for name in SETS:
    col = f"p_{name}"
    q5 = W.groupby("q")[col].transform(
        lambda s: pd.qcut(s, 5, labels=False, duplicates="drop"))
    g = W[q5 == 4]; g2 = g[g.date >= CUT]
    rows.append({"features": name, "n": len(g),
                 "avgR full": round(g.R.mean(), 3),
                 "win% full": round(100 * (g.p > 0).mean(), 1),
                 "avgR last2y": round(g2.R.mean(), 3),
                 "win% last2y": round(100 * (g2.p > 0).mean(), 1)})
print(pd.DataFrame(rows).to_string(index=False))
