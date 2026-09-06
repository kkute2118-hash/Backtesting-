"""Phase 14 - the underlying principle behind the score's inversion."""
import numpy as np, pandas as pd
import evaluate as E
pd.set_option("display.width", 240)

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
d = d[d.gap_through == 0].copy()
TR = d[d.date < "2024-04-01"]; VA = d[(d.date >= "2024-04-01") & (d.date < "2025-07-01")]
TE = d[d.date >= "2025-07-01"]

print("Is the GTF trade score a proxy for zone thinness?")
print(d.groupby("score").agg(n=("risk_pct", "size"),
                             median_risk_pct=("risk_pct", "median"),
                             median_n_base=("n_base", "median")).round(2).to_string())
print("\ncorr(score, risk_pct) =", round(d.score.corr(d.risk_pct), 3))
print("corr(n_base, risk_pct) =", round(d.n_base.corr(d.risk_pct), 3))

print("\n" + "=" * 100)
print("Is the zone-width effect just the fixed cost, or something real?")
print("=" * 100)
rows = []
for cost, lbl in ((E.COST_PCT, "with 0.23% round-trip cost"), (0.0, "with ZERO cost")):
    for lo, hi in ((0, 1.5), (1.5, 2.5), (2.5, 4.0), (4.0, 6.0), (6.0, 100)):
        s = d[(d.risk_pct >= lo) & (d.risk_pct < hi)]
        r2 = E.r_of(s, "R", 2.0, cost_pct=cost)
        r3 = E.r_of(s, "R", 3.0, cost_pct=cost)
        rows.append({"cost": lbl, "risk%": f"{lo}-{hi}", "n": len(s),
                     "avgR@2R": r2.mean(), "avgR@3R": r3.mean(),
                     "win%@2R": 100 * (r2 > 0).mean(),
                     "stop-out%": 100 * ((s.stop_bar >= 0) & (s.stop_bar <= 60)).mean(),
                     "stop on bar0%": 100 * (s.stop_bar == 0).mean(),
                     "cost in R": cost / s.risk_pct.mean()})
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n" + "=" * 100)
print("Feature screen CONTROLLED for zone width (within risk_pct quintiles, train)")
print("=" * 100)
TR = TR.assign(R=E.r_of(TR, "R", 2.0), rq=pd.qcut(TR.risk_pct, 5, labels=False))
VA = VA.assign(R=E.r_of(VA, "R", 2.0), rq=pd.qcut(VA.risk_pct, 5, labels=False))
TE = TE.assign(R=E.r_of(TE, "R", 2.0), rq=pd.qcut(TE.risk_pct, 5, labels=False))

def within(df, f):
    """mean R of the top feature quintile minus the bottom, averaged over
    zone-width quintiles so width cannot drive the answer"""
    out = []
    for q in range(5):
        s = df[df.rq == q]
        if len(s) < 500 or s[f].nunique() < 5:
            continue
        try:
            fq = pd.qcut(s[f], 5, labels=False, duplicates="drop")
        except Exception:
            continue
        g = s.assign(fq=fq).groupby("fq")["R"].mean()
        if len(g) >= 5:
            out.append(g.iloc[-1] - g.iloc[0])
    return np.mean(out) if out else np.nan

feats = ["score", "n_base", "legout_n", "arrival", "closing_ok", "legout_atr",
         "atr_pct", "zone_age", "relvol", "turnover_cr", "prev_close_pct",
         "rsi14", "dist_ema200_atr", "dist_ema20_atr", "target_r_available",
         "w_trend50", "d_trend", "gap_in"]
rows = []
for f in feats:
    a, b, c = within(TR, f), within(VA, f), within(TE, f)
    rows.append({"feature": f, "spread_tr": a, "spread_va": b, "spread_te": c,
                 "agree3": bool(np.isfinite(a) and np.isfinite(b) and np.isfinite(c)
                                and np.sign(a) == np.sign(b) == np.sign(c))})
t = pd.DataFrame(rows).sort_values("spread_tr")
print(t.round(3).to_string(index=False))
print("\nfeatures that survive controlling for zone width, in all three periods:")
print(t[t.agree3].round(3).to_string(index=False))
