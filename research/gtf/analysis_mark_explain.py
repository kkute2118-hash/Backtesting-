"""What the mark is made of, and whether it means what it says.

Two questions a marking system has to answer before anyone trades it:
  does a high mark actually correspond to a higher win rate, out of sample?
  what is the model looking at when it gives one?
"""
import numpy as np, pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.ensemble import HistGradientBoostingClassifier
import rank as RK
pd.set_option("display.width", 240)
CUT = pd.Timestamp("2024-09-04")

V = pd.read_parquet("/tmp/gtf/pool_pwin.parquet"); V["date"] = pd.to_datetime(V["date"])
V["q"] = V.date.dt.to_period("Q")
# the mark is the percentile of pwin within its own quarter's scoring
V["mark"] = V.groupby("q")["pwin"].rank(pct=True) * 100

print("=" * 96)
print("1. CALIBRATION - does a higher mark really win more often? (out of sample)")
print("=" * 96)
bins = [0, 50, 75, 90, 95, 99, 100]
V["band"] = pd.cut(V["mark"], bins, include_lowest=True)
for lab, g in (("full window", V), ("last 2 years", V[V.date >= CUT])):
    t = g.groupby("band", observed=True).agg(
        n=("p", "size"), win=("p", lambda s: 100 * (s > 0).mean()),
        avgR=("R", "mean"), avg_pct=("p", "mean"))
    print(f"\n{lab}")
    print(t.round(2).to_string())

print("\n" + "=" * 96)
print("2. WHAT DRIVES A HIGH MARK - permutation importance, measured on a")
print("   quarter the model never trained on")
print("=" * 96)
d = RK.prepare(); d = d[d.turnover_cr >= 25].copy()
d["q"] = d.date.dt.to_period("Q"); d["win"] = (d.p > 0).astype(int)
feats = [f for f in RK.FEATS + [c for c in d.columns if c.startswith("is_")] if f in d.columns]
qq = sorted(d.q.unique())[-3]                       # a recent, fully resolved quarter
past = d[(d.q < qq) & (d.date < qq.start_time - pd.Timedelta(days=RK.RESOLVE_DAYS))]
use = [f for f in feats if past[f].notna().sum() > 100 and past[f].nunique() > 1]
m = HistGradientBoostingClassifier(max_depth=3, max_iter=300, learning_rate=0.05,
                                   min_samples_leaf=100, l2_regularization=1.0,
                                   random_state=0).fit(past[use].to_numpy(), past.win.to_numpy())
test = d[d.q == qq]
r = permutation_importance(m, test[use].to_numpy(), test.win.to_numpy(),
                           n_repeats=5, random_state=0, scoring="roc_auc")
imp = pd.DataFrame({"feature": use, "importance": r.importances_mean}) \
        .sort_values("importance", ascending=False).head(12)
print(f"scored on {qq}, {len(test)} candidates, trained on {len(past)}")
print(imp.round(4).to_string(index=False))

print("\n" + "=" * 96)
print("3. WHAT A MARKED CANDIDATE LOOKS LIKE vs an unmarked one")
print("=" * 96)
cols = ["atr_pct", "turnover_cr", "rsi14", "dist_ema200_atr", "pct_from_52w_high",
        "ret_20d", "ret_120d", "w_slope", "vol20d", "src_score"]
hi = V[V["mark"] >= 99]; lo = V[V["mark"] <= 50]
cmp = pd.DataFrame({"mark >= 99": hi[cols].median(), "mark <= 50": lo[cols].median()})
cmp["difference"] = cmp["mark >= 99"] - cmp["mark <= 50"]
print(cmp.round(2).to_string())
print(f"\nsource mix at mark >= 99:")
print((100 * hi.source.value_counts(normalize=True)).round(1).to_string())
