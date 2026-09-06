"""Head-to-head: does the learned score beat the five simple rules, at the same
trade count, on data neither has seen? And is it just buying illiquid names?"""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
pd.set_option("display.width", 250)
EXIT = "x_fix_2_8"

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
x = pd.read_parquet("/tmp/gtf/exits.parquet")
d = pd.concat([d, x[[c for c in x.columns if c.startswith("x_")]]], axis=1)
c = pd.read_parquet("/tmp/gtf/control.parquet"); c["date"] = pd.to_datetime(c["date"])
cx = pd.read_parquet("/tmp/gtf/control_exits.parquet")
c = pd.concat([c.reset_index(drop=True),
               cx[[k for k in cx.columns if k.startswith("x_")]].reset_index(drop=True)], axis=1)
d = d[(d.gap_through == 0) & d[EXIT].notna()].copy(); d["y"] = d[EXIT]

FEATS = ["risk_pct", "zone_h_pct", "n_base", "legout_n", "gap", "closing_ok",
         "legout_atr", "zone_age", "arrival", "score", "atr_pct", "relvol",
         "rsi14", "dist_ema200_atr", "dist_ema50_atr", "dist_ema20_atr",
         "prev_close_pct", "gap_in", "turnover_cr", "target_r_available",
         "w_trend50", "w_trend10", "m_trend50", "d_trend", "m_curve", "w_curve",
         "coincide", "risk_atr"]
TR = d[d.date < "2024-04-01"].copy()
VA = d[(d.date >= "2024-04-01") & (d.date < "2025-07-01")].copy()
TE = d[d.date >= "2025-07-01"].copy()
q = lambda f, p: float(np.nanpercentile(TR[f], p))
TH = dict(atr=q("atr_pct", 50), legout=q("legout_atr", 50),
          risk=q("risk_pct", 40), speed=q("prev_close_pct", 50))
def C12(z):
    return (z.risk_pct.ge(TH["risk"]) & z.legout_atr.ge(TH["legout"])
            & z.atr_pct.ge(TH["atr"]) & z.prev_close_pct.ge(TH["speed"])
            & z.dist_ema200_atr.le(0.96))

model = HistGradientBoostingRegressor(max_depth=3, max_iter=250, learning_rate=0.05,
                                      min_samples_leaf=80, l2_regularization=1.0,
                                      random_state=0).fit(TR[FEATS].to_numpy(), TR.y.to_numpy())
for S in (TR, VA, TE):
    S["pred"] = model.predict(S[FEATS].to_numpy())
CUT = float(np.percentile(TR.pred, 90))     # the threshold is set on train only
print(f"model score threshold (train 90th pct) = {CUT:.3f}\n")

def st(s, label):
    s = np.asarray(s, float); s = s[np.isfinite(s)]
    if len(s) < 20: return {"strategy": label, "n": len(s)}
    w = s[s > 0]; l = s[s <= 0]; eq = np.cumsum(s)
    return {"strategy": label, "n": len(s), "win%": 100 * len(w) / len(s),
            "avg%": s.mean(), "PF": w.sum() / -l.sum() if l.sum() < 0 else np.inf,
            "maxDD%": float((eq - np.maximum.accumulate(eq)).min())}

VARIANTS = {
    "R1 five rules (C12)": lambda z: C12(z),
    "R2 learned score only": lambda z: z.pred >= CUT,
    "R3 five rules AND score": lambda z: C12(z) & (z.pred >= CUT),
    "R4 five rules OR score": lambda z: C12(z) | (z.pred >= CUT),
}
rows = []
for name, fn in VARIANTS.items():
    for nm, S in (("train", TR), ("val", VA), ("test", TE)):
        s = S[fn(S)]
        rows.append({**st(s.y, name), "split": nm})
t = pd.DataFrame(rows)
print("=" * 118)
print(f"HEAD TO HEAD, exit = {EXIT[2:]} (stop entry-2ATR, target entry+8ATR, 60-bar cap)")
print("=" * 118)
print(t.pivot_table(index="strategy", columns="split",
                    values=["n", "avg%", "PF", "win%"], sort=False)
      .reindex(columns=["train", "val", "test"], level=1).round(2).to_string())

print("\n" + "=" * 118)
print("Is the learned score just buying illiquid names?")
print("=" * 118)
for nm, S in (("all arrivals", TR), ("C12", TR[C12(TR)]), ("learned top decile", TR[TR.pred >= CUT])):
    print(f"  {nm:<20} median turnover {S.turnover_cr.median():>7.1f} Cr   "
          f"p10 {S.turnover_cr.quantile(.10):>6.1f}   "
          f"share under 5 Cr/day: {100*(S.turnover_cr < 5).mean():.1f}%")

print("\nwith a hard liquidity floor of 10 Cr/day median turnover:")
rows = []
for name, fn in VARIANTS.items():
    for nm, S in (("train", TR), ("val", VA), ("test", TE)):
        s = S[fn(S) & S.turnover_cr.ge(10)]
        rows.append({**st(s.y, name), "split": nm})
print(pd.DataFrame(rows).pivot_table(index="strategy", columns="split",
                                     values=["n", "avg%", "PF"], sort=False)
      .reindex(columns=["train", "val", "test"], level=1).round(2).to_string())

print("\n" + "=" * 118)
print("Placebo, same exit policy")
print("=" * 118)
for nm, m in (("train", c.date < "2024-04-01"),
              ("val", (c.date >= "2024-04-01") & (c.date < "2025-07-01")),
              ("test", c.date >= "2025-07-01")):
    print(" ", {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in st(c[m][EXIT], f"placebo {nm}").items()})
