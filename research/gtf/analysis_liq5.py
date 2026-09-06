"""Significance for the one rule that survived, plus what it is worth."""
import numpy as np, pandas as pd
pd.set_option("display.width", 220)

d = pd.read_parquet("/tmp/gtf/liq.parquet"); d["date"] = pd.to_datetime(d["date"])
c = pd.read_parquet("/tmp/gtf/liq_control.parquet"); c["date"] = pd.to_datetime(c["date"])
rev = d[d.side.eq("long") & d.kind.isin(["grab", "sweep"])].copy()
pl = (c[c.side.eq("long") & c.kind.isin(["grab", "sweep"]) & c.what.eq("placebo_fwd")]
      .groupby(["symbol", "date", "kind"])["p_time"].mean().rename("placebo"))
rev = rev.merge(pl, on=["symbol", "date", "kind"], how="left")
rev["diff"] = rev.p_time - rev.placebo
sel = rev[rev.weekly_slope_pct > 5]


def blockboot(x, blocks, n=4000, seed=11):
    """Resample whole months. Signals cluster, so rows are not independent."""
    x = np.asarray(x, float); b = np.asarray(blocks)
    ok = np.isfinite(x); x, b = x[ok], b[ok]
    keys = np.unique(b); idx = {k: np.nonzero(b == k)[0] for k in keys}
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    for i in range(n):
        pick = rng.choice(keys, len(keys), replace=True)
        out[i] = x[np.concatenate([idx[k] for k in pick])].mean()
    return out


print("=" * 92)
print("THE SURVIVING RULE: grab or sweep, long, weekly 20-SMA up more than 5% over 6 weeks")
print("=" * 92)
for lab, g in (("full window", sel),
               ("2021-2023 (train)", sel[sel.date < "2024-01-01"]),
               ("2024-2026 (held out)", sel[sel.date >= "2024-01-01"]),
               ("last 2 years", sel[sel.date >= "2024-09-04"])):
    if len(g) < 40:
        print(f"{lab:<24} n={len(g)} - too few")
        continue
    bs = blockboot(g["diff"], g.date.dt.to_period("M").astype(str))
    lo, hi = np.percentile(bs, [2.5, 97.5])
    print(f"{lab:<24} n={len(g):>4}  raw {g.p_time.mean():+5.2f}%  "
          f"placebo {g.placebo.mean():+5.2f}%  edge {g['diff'].mean():+5.2f} pp  "
          f"95% CI [{lo:+.2f}, {hi:+.2f}]  P(edge>0)={100*(bs>0).mean():.0f}%")

print(f"\nwin rate {100*(sel.p_time>0).mean():.1f}%   median {sel.p_time.median():+.2f}%   "
      f"~{len(sel)/5.3:.0f} signals a year across 472 stocks")

print("\n" + "=" * 92)
print("HOW MUCH OF THIS IS JUST 'BUY STRONG STOCKS'?")
print("   same weekly-trend filter, but entering at a random bar instead of the setup")
print("=" * 92)
print(f"setup entries   {sel.p_time.mean():+.2f}%")
print(f"random entries  {sel.placebo.mean():+.2f}%   <- the trend filter alone")
print(f"the pattern is worth {sel['diff'].mean():+.2f} pp of that")

print("\n" + "=" * 92)
print("SENSITIVITY: is 5% a cliff or a slope?")
print("=" * 92)
for thr in (0, 2, 5, 8, 12):
    g = rev[rev.weekly_slope_pct > thr]
    h = g[g.date >= "2024-01-01"]
    print(f"  weekly slope > {thr:>2}%   n={len(g):>4}  edge {g['diff'].mean():+5.2f} pp"
          f"   held-out n={len(h):>4} edge {h['diff'].mean():+5.2f} pp")
