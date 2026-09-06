"""Choose on pre-2024, read the held-out period once.

Everything above was measured on the whole window, which is how a filter
that only ever worked in one regime gets mistaken for an edge. So: rank
candidate refinements on 2021-2023 only, take the best one, and look at
2024-2026 exactly once. Whatever that number is, it is the answer.

Edge is always measured against the matched placebo, not against zero,
because a long-only rule in a rising market beats zero for free.
"""
import numpy as np, pandas as pd
pd.set_option("display.width", 220)

d = pd.read_parquet("/tmp/gtf/liq.parquet"); d["date"] = pd.to_datetime(d["date"])
c = pd.read_parquet("/tmp/gtf/liq_control.parquet")
c["date"] = pd.to_datetime(c["date"])
TRAIN = d.date < "2024-01-01"

rev = d[d.side.eq("long") & d.kind.isin(["grab", "sweep"])].copy()
crev = c[c.side.eq("long") & c.kind.isin(["grab", "sweep"]) & c.what.eq("placebo_fwd")]
# placebo mean per (symbol,date) so a filtered subset gets ITS OWN placebo
pl = crev.groupby(["symbol", "date", "kind"])["p_time"].mean().rename("placebo")
rev = rev.merge(pl, on=["symbol", "date", "kind"], how="left")
print(f"{len(rev)} reversal setups, {rev.placebo.notna().mean():.1%} matched to a placebo")

CAND = {
    "all reversals": lambda x: x.index.notna(),
    "grab only": lambda x: x.kind.eq("grab"),
    "sweep only": lambda x: x.kind.eq("sweep"),
    "equal lows (2+ touches)": lambda x: x.level_touches >= 2,
    "low-resistance level": lambda x: x.level_res.eq("low_res"),
    "high-resistance level": lambda x: x.level_res.eq("high_res"),
    "quiet take (vol < 1.5x)": lambda x: x.take_relvol < 1.5,
    "loud take (vol >= 2x)": lambda x: x.take_relvol >= 2,
    "momentum confirm >= 3x": lambda x: x.conf_body_mult >= 3,
    "weekly trend up": lambda x: x.weekly_slope_pct > 0,
    "weekly trend sharply up": lambda x: x.weekly_slope_pct > 5,
    "below the 200 EMA": lambda x: x.dist_ema200_atr < 0,
    "shallow poke (< 0.5 ATR)": lambda x: x.poke_atr < 0.5,
    "fresh level (< 40 bars)": lambda x: x.level_age < 40,
    "liquid (turnover > 10cr)": lambda x: x.turnover_cr > 10,
    "quiet + low-res + weekly up": lambda x: (x.take_relvol < 1.5)
        & x.level_res.eq("low_res") & (x.weekly_slope_pct > 0),
    "quiet + equal lows": lambda x: (x.take_relvol < 1.5) & (x.level_touches >= 2),
    "quiet + liquid + weekly up": lambda x: (x.take_relvol < 1.5)
        & (x.turnover_cr > 10) & (x.weekly_slope_pct > 0),
}

def edge(g):
    m = g.placebo.notna()
    if m.sum() < 60: return np.nan, int(m.sum()), np.nan
    return (round(g.loc[m, "p_time"].mean() - g.loc[m, "placebo"].mean(), 2),
            int(m.sum()), round(g.loc[m, "p_time"].mean(), 2))

print("\n" + "=" * 96)
print("RANKED ON 2021-2023 ONLY (edge over matched placebo, percentage points)")
print("=" * 96)
tr = rev[rev.date < "2024-01-01"]
rows = []
for name, f in CAND.items():
    e, n, raw = edge(tr[f(tr)])
    rows.append({"refinement": name, "n": n, "train raw%": raw, "train edge": e})
t = pd.DataFrame(rows).sort_values("train edge", ascending=False)
print(t.to_string(index=False))

best = t.iloc[0]["refinement"]
print(f"\nbest on train: {best!r}")

print("\n" + "=" * 96)
print("HELD OUT: 2024-01-01 onwards, read once")
print("=" * 96)
ho = rev[rev.date >= "2024-01-01"]
rows = []
for name, f in CAND.items():
    e, n, raw = edge(ho[f(ho)])
    et, nt, rt = edge(tr[f(tr)])
    rows.append({"refinement": name, "train edge": et, "held-out n": n,
                 "held-out raw%": raw, "held-out edge": e,
                 "kept?": "yes" if (pd.notna(e) and pd.notna(et) and e > 0 and et > 0) else "no"})
print(pd.DataFrame(rows).to_string(index=False))

r = [x for x in rows if x["refinement"] == best][0]
print(f"\nthe refinement chosen on train scored {r['held-out edge']} on held-out data "
      f"(n={r['held-out n']}, raw {r['held-out raw%']}%)")
kept = sum(1 for x in rows if x["kept?"] == "yes")
print(f"{kept} of {len(rows)} refinements had a positive edge in both halves")
