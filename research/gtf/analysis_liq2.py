"""The setups against their matched placebo and their same-bar mirror."""
import numpy as np, pandas as pd
pd.set_option("display.width", 250)

d = pd.read_parquet("/tmp/gtf/liq.parquet"); d["date"] = pd.to_datetime(d["date"])
c = pd.read_parquet("/tmp/gtf/liq_control.parquet"); c["date"] = pd.to_datetime(c["date"])
CUT = "2024-09-04"


def boot(x, g, n=2000, seed=7):
    """Month-block bootstrap: signals cluster in time, so rows are not independent."""
    x = np.asarray(x, float); g = np.asarray(g)
    ok = np.isfinite(x); x, g = x[ok], g[ok]
    if len(x) < 40: return np.nan, np.nan
    keys = np.unique(g)
    idx = {k: np.nonzero(g == k)[0] for k in keys}
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    for i in range(n):
        pick = rng.choice(keys, len(keys), replace=True)
        out[i] = np.concatenate([idx[k] for k in pick]).mean() * 0 + \
                 x[np.concatenate([idx[k] for k in pick])].mean()
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


print("=" * 116)
print("SETUP vs MATCHED PLACEBO (same symbol, same month, same risk, random bar)")
print("and vs the SAME-BAR MIRROR (identical bar, opposite direction)")
print("all with no target, 60-bar time exit, costs in")
print("=" * 116)
rows = []
for (k, s), g in d.groupby(["kind", "side"]):
    cc = c[c.kind.eq(k) & c.side.eq(s)]
    pl = cc.loc[cc.what.eq("placebo"), "p_time"]
    mi = cc.loc[cc.what.eq("mirror"), "p_time"]
    lo, hi = boot(g.p_time, g.date.dt.to_period("M").astype(str))
    rows.append({"pattern": f"{k} {s}", "n": len(g),
                 "setup%": round(g.p_time.mean(), 2),
                 "95% CI": f"[{lo:+.2f}, {hi:+.2f}]",
                 "placebo%": round(pl.mean(), 2),
                 "edge vs placebo": round(g.p_time.mean() - pl.mean(), 2),
                 "mirror%": round(mi.mean(), 2),
                 "setup - mirror": round(g.p_time.mean() - mi.mean(), 2)})
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 116)
print("SAME, LAST 2 YEARS ONLY")
print("=" * 116)
rows = []
for (k, s), g0 in d.groupby(["kind", "side"]):
    g = g0[g0.date >= CUT]
    cc = c[c.kind.eq(k) & c.side.eq(s) & (c.date >= CUT)]
    if len(g) < 40: continue
    pl = cc.loc[cc.what.eq("placebo"), "p_time"]
    mi = cc.loc[cc.what.eq("mirror"), "p_time"]
    lo, hi = boot(g.p_time, g.date.dt.to_period("M").astype(str))
    rows.append({"pattern": f"{k} {s}", "n": len(g),
                 "setup%": round(g.p_time.mean(), 2),
                 "95% CI": f"[{lo:+.2f}, {hi:+.2f}]",
                 "placebo%": round(pl.mean(), 2),
                 "edge vs placebo": round(g.p_time.mean() - pl.mean(), 2),
                 "mirror%": round(mi.mean(), 2)})
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 116)
print("THE RUN, GRADED BY THE SPEAKER'S OWN DISCRIMINATORS, vs PLACEBO")
print("   'body at least twice the previous candle', volume, small wick")
print("=" * 116)
r = d[d.kind.eq("run") & d.side.eq("long")].copy()
cr = c[c.kind.eq("run") & c.side.eq("long") & c.what.eq("placebo")]
base = cr.p_time.mean()
print(f"placebo for these rows: {base:+.2f}%\n")
rows = []
for lab, m in (("all runs", r.index.notna()),
               ("body >= 3x prev", r.conf_body_mult >= 3),
               ("body >= 5x prev", r.conf_body_mult >= 5),
               ("volume >= 3x", r.conf_relvol >= 3),
               ("body>=3x AND vol>=3x", (r.conf_body_mult >= 3) & (r.conf_relvol >= 3)),
               ("+ level was high-resistance", (r.conf_body_mult >= 3) & (r.conf_relvol >= 3)
                & r.level_res.eq("high_res")),
               ("+ weekly trend up", (r.conf_body_mult >= 3) & (r.conf_relvol >= 3)
                & r.level_res.eq("high_res") & (r.weekly_slope_pct > 0))):
    g = r[m]
    if len(g) < 30: continue
    lo, hi = boot(g.p_time, g.date.dt.to_period("M").astype(str))
    g2 = g[g.date >= CUT]
    rows.append({"filter": lab, "n": len(g),
                 "avg%": round(g.p_time.mean(), 2),
                 "95% CI": f"[{lo:+.2f}, {hi:+.2f}]",
                 "vs placebo": round(g.p_time.mean() - base, 2),
                 "win%": round(100 * (g.p_time > 0).mean(), 1),
                 "n last2y": len(g2),
                 "last2y%": round(g2.p_time.mean(), 2) if len(g2) >= 30 else np.nan})
print(pd.DataFrame(rows).to_string(index=False))
