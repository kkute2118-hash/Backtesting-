"""The honest test: expanding-window walk-forward.

At the start of every quarter the model is refit on data available up to that
point and nothing later, then used to score that quarter only. No fold ever
sees its own future. This removes the "fit once on train, then peek" objection
and is the closest thing to how the system would actually have run.
"""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
pd.set_option("display.width", 250)
EXIT = "x_fix_2_8"
MIN_TRAIN = 6000          # do not fit until there is enough history

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
x = pd.read_parquet("/tmp/gtf/exits.parquet")
d = pd.concat([d, x[[c for c in x.columns if c[:2] in ("x_", "b_")]]], axis=1)
d = d[(d.gap_through == 0) & d[EXIT].notna()].copy().sort_values("date").reset_index(drop=True)
d["y"] = d[EXIT]
c = pd.read_parquet("/tmp/gtf/control.parquet"); c["date"] = pd.to_datetime(c["date"])
cx = pd.read_parquet("/tmp/gtf/control_exits.parquet")
c = pd.concat([c.reset_index(drop=True),
               cx[[k for k in cx.columns if k.startswith("x_")]].reset_index(drop=True)], axis=1)

FEATS = ["risk_pct", "zone_h_pct", "n_base", "legout_n", "gap", "closing_ok",
         "legout_atr", "zone_age", "arrival", "score", "atr_pct", "relvol",
         "rsi14", "dist_ema200_atr", "dist_ema50_atr", "dist_ema20_atr",
         "prev_close_pct", "gap_in", "turnover_cr", "target_r_available",
         "w_trend50", "w_trend10", "m_trend50", "d_trend", "m_curve", "w_curve",
         "coincide", "risk_atr"]

d["q"] = d.date.dt.to_period("Q")
quarters = sorted(d.q.unique())
d["pred"] = np.nan
d["thr"] = np.nan
d["rule_thr_risk"] = np.nan
fitted = 0
for qq in quarters:
    past = d[d.q < qq]
    # a trade needs 60 bars to resolve, so anything opened in the last ~3 months
    # of `past` has not finished yet and must not be trained on
    past = past[past.date < (qq.start_time - pd.Timedelta(days=95))]
    if len(past) < MIN_TRAIN:
        continue
    # a column that is entirely NaN or constant in this slice cannot be binned
    use = [f for f in FEATS if past[f].notna().sum() > 50 and past[f].nunique() > 1]
    m = HistGradientBoostingRegressor(max_depth=3, max_iter=250, learning_rate=0.05,
                                      min_samples_leaf=80, l2_regularization=1.0,
                                      random_state=0).fit(past[use].to_numpy(),
                                                          past.y.to_numpy())
    sel = d.q == qq
    d.loc[sel, "pred"] = m.predict(d.loc[sel, use].to_numpy())
    d.loc[sel, "thr"] = float(np.percentile(m.predict(past[use].to_numpy()), 90))
    for f, p in (("risk_pct", 40), ("legout_atr", 50), ("atr_pct", 50), ("prev_close_pct", 50)):
        d.loc[sel, f"th_{f}"] = float(np.nanpercentile(past[f], p))
    fitted += 1
print(f"quarters scored out of sample: {fitted} of {len(quarters)}")

W = d[d.pred.notna()].copy()
print(f"walk-forward window: {W.date.min().date()} .. {W.date.max().date()}   {len(W)} arrivals\n")

rules = (W.risk_pct >= W.th_risk_pct) & (W.legout_atr >= W.th_legout_atr) \
        & (W.atr_pct >= W.th_atr_pct) & (W.prev_close_pct >= W.th_prev_close_pct) \
        & (W.dist_ema200_atr <= 0.96)
score = W.pred >= W.thr

def st(s, label):
    s = np.asarray(s, float); s = s[np.isfinite(s)]
    if len(s) < 10: return {"strategy": label, "n": len(s)}
    w = s[s > 0]; l = s[s <= 0]; eq = np.cumsum(s)
    return {"strategy": label, "n": len(s), "win%": round(100 * len(w) / len(s), 1),
            "avg%": round(s.mean(), 2),
            "PF": round(w.sum() / -l.sum(), 2) if l.sum() < 0 else np.inf,
            "maxDD%": round(float((eq - np.maximum.accumulate(eq)).min()), 0)}

print("=" * 110)
print("FULLY WALK-FORWARD RESULTS - every score produced by a model that saw only its past")
print("=" * 110)
cm = c[(c.date >= W.date.min()) & (c.date <= W.date.max())]
for nm, s in (("every arrival", W.y), ("matched placebo", cm[EXIT]),
              ("rules only", W[rules].y), ("score only", W[score].y),
              ("rules AND score", W[rules & score].y),
              ("rules AND score, >=10Cr", W[rules & score & W.turnover_cr.ge(10)].y)):
    print(" ", st(s, nm))

def boot(sub, n=2000, seed=5):
    s = pd.DataFrame({"p": sub.y.to_numpy(),
                      "k": sub.date.dt.to_period("M").astype(str).to_numpy()})
    s = s[np.isfinite(s.p)]
    g = [v["p"].to_numpy() for _, v in s.groupby("k")]
    rng = np.random.default_rng(seed)
    return np.percentile([np.concatenate([g[i] for i in rng.integers(0, len(g), len(g))]).mean()
                          for _ in range(n)], [2.5, 97.5])

for nm, sub in (("rules only", W[rules]), ("rules AND score", W[rules & score])):
    lo, hi = boot(sub)
    print(f"\n{nm}: month-block bootstrap 95% CI on mean % = [{lo:+.2f}, {hi:+.2f}]")

print("\nby year, walk-forward:")
for nm, sub in (("rules only", W[rules]), ("rules AND score", W[rules & score])):
    g = sub.set_index("date").groupby(pd.Grouper(freq="YE"))["y"]
    print(f"  {nm}")
    print(pd.DataFrame({"n": g.size(), "avg%": g.mean(),
                        "win%": g.apply(lambda s: 100 * (s > 0).mean())}).round(2).to_string())
W.to_parquet("/tmp/gtf/walkforward.parquet", index=False)
print("\nsaved /tmp/gtf/walkforward.parquet")
