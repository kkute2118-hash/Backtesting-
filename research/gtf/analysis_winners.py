"""What separates the winners? Two ways, both on TRAIN only.

(1) The literal reading: describe the big winners and see how they differ.
    This is the overfitting trap - a winner is defined by its outcome - so it
    is reported as a hypothesis generator, never as a rule.
(2) The disciplined version: fit a model that never sees the outcome it is
    scored on, using cross-validation inside train, and check whether its
    score is monotone in outcome on data it has never touched.
"""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold
from sklearn.inspection import permutation_importance
pd.set_option("display.width", 250)

EXIT = "x_fix_2_8"

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
x = pd.read_parquet("/tmp/gtf/exits.parquet")
d = pd.concat([d, x[[c for c in x.columns if c.startswith("x_")]]], axis=1)
d = d[(d.gap_through == 0) & d[EXIT].notna()].copy()
d["y"] = d[EXIT]

FEATS = ["risk_pct", "zone_h_pct", "n_base", "legout_n", "gap", "closing_ok",
         "legout_atr", "zone_age", "arrival", "score", "atr_pct", "relvol",
         "rsi14", "dist_ema200_atr", "dist_ema50_atr", "dist_ema20_atr",
         "prev_close_pct", "gap_in", "turnover_cr", "target_r_available",
         "w_trend50", "w_trend10", "m_trend50", "d_trend", "m_curve", "w_curve",
         "coincide", "risk_atr"]
TR = d[d.date < "2024-04-01"].copy()
VA = d[(d.date >= "2024-04-01") & (d.date < "2025-07-01")].copy()
TE = d[d.date >= "2025-07-01"].copy()
print(f"train {len(TR)}  val {len(VA)}  test {len(TE)}   exit = {EXIT[2:]}\n")

# ---------------------------------------------------------------- (1) literal
print("=" * 118)
print("(1) THE LITERAL READING - top decile of outcomes vs the rest, TRAIN only")
print("    Read this as a list of hypotheses, not rules. Conditioning on the")
print("    outcome is how strategies get overfitted.")
print("=" * 118)
cut = TR.y.quantile(0.90)
win = TR[TR.y >= cut]; rest = TR[TR.y < cut]
rows = []
for f in FEATS:
    a, b = win[f].dropna(), rest[f].dropna()
    if len(a) < 50 or a.nunique() < 3:
        continue
    pooled = np.sqrt((a.var() + b.var()) / 2)
    rows.append({"feature": f, "winners_median": a.median(), "rest_median": b.median(),
                 "cohens_d": (a.mean() - b.mean()) / pooled if pooled > 0 else np.nan})
t = pd.DataFrame(rows).reindex(pd.DataFrame(rows).cohens_d.abs().sort_values(ascending=False).index)
print(t.round(3).head(12).to_string(index=False))
print("\nEvery one of these separations is measured on the same data that defined")
print("'winner'. The only honest use is to feed them to (2).")

# ---------------------------------------------------------------- (2) model
print("\n" + "=" * 118)
print("(2) THE DISCIPLINED VERSION - gradient boosting, 5-fold grouped by month")
print("    inside train, so no fold scores a trade whose neighbours it trained on")
print("=" * 118)
Xtr = TR[FEATS].to_numpy(); ytr = TR.y.to_numpy()
grp = TR.date.dt.to_period("M").astype(str).to_numpy()
oof = np.full(len(TR), np.nan)
gkf = GroupKFold(n_splits=5)
for tr_i, te_i in gkf.split(Xtr, ytr, groups=grp):
    m = HistGradientBoostingRegressor(max_depth=3, max_iter=250, learning_rate=0.05,
                                      min_samples_leaf=80, l2_regularization=1.0,
                                      random_state=0)
    m.fit(Xtr[tr_i], ytr[tr_i])
    oof[te_i] = m.predict(Xtr[te_i])
TR["pred"] = oof
print("out-of-fold decile of predicted return, inside train:")
TR["dec"] = pd.qcut(TR.pred, 10, labels=False, duplicates="drop")
print(TR.groupby("dec").agg(n=("y", "size"), pred=("pred", "mean"),
                            actual=("y", "mean"),
                            win=("y", lambda s: 100 * (s > 0).mean())).round(2).to_string())
print(f"\nout-of-fold rank correlation: {pd.Series(oof).corr(TR.y, method='spearman'):.4f}")

full = HistGradientBoostingRegressor(max_depth=3, max_iter=250, learning_rate=0.05,
                                     min_samples_leaf=80, l2_regularization=1.0,
                                     random_state=0).fit(Xtr, ytr)
print("\npermutation importance (train, top 10):")
pi = permutation_importance(full, Xtr, ytr, n_repeats=5, random_state=0, n_jobs=4)
imp = pd.DataFrame({"feature": FEATS, "importance": pi.importances_mean}
                   ).sort_values("importance", ascending=False)
print(imp.head(10).round(4).to_string(index=False))

print("\n" + "=" * 118)
print("Does the score survive on data the model has never seen?")
print("=" * 118)
for nm, S in (("validation", VA), ("test", TE)):
    S = S.copy(); S["pred"] = full.predict(S[FEATS].to_numpy())
    S["dec"] = pd.qcut(S.pred, 10, labels=False, duplicates="drop")
    g = S.groupby("dec").agg(n=("y", "size"), actual=("y", "mean"),
                             win=("y", lambda s: 100 * (s > 0).mean()))
    print(f"\n{nm}:  spearman {S.pred.corr(S.y, method='spearman'):+.4f}")
    print(g.round(2).to_string())
    top, bot = g.actual.iloc[-1], g.actual.iloc[0]
    print(f"  top decile {top:+.2f}%  bottom decile {bot:+.2f}%  spread {top-bot:+.2f}%")
