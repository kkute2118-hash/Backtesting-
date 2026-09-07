"""How many independent episodes is the "fear filter" actually measured on?

Buying when breadth is under 30% returned +0.472 R against a pool average of
-0.148, and the top fifth by P(win) returned +0.682 with a 45% win rate. Those
are the best numbers in this entire project, which is exactly why they need
the episode count before anything else. 11,336 candidates that all sit inside
one drawdown is a sample of one, not of 11,336.
"""
import numpy as np, pandas as pd
pd.set_option("display.width", 240)
CUT = pd.Timestamp("2024-09-04")

V = pd.read_parquet("/tmp/gtf/pool_pwin.parquet"); V["date"] = pd.to_datetime(V["date"])
R = pd.read_parquet("/tmp/gtf/regime.parquet")
V = V.join(R, on="date")
day = R.dropna(subset=["breadth_ma20"]).copy()


def episodes(mask, gap=10):
    """Contiguous stretches where the rule is on, merged across short gaps."""
    on = mask[mask].index
    if not len(on):
        return []
    out = [[on[0], on[0]]]
    for d in on[1:]:
        if (d - out[-1][1]).days <= gap:
            out[-1][1] = d
        else:
            out.append([d, d])
    return out


print("=" * 108)
print("EPISODE COUNT - the honest sample size for a regime rule")
print("=" * 108)
for name, m in (("index below its 200 DMA", day.idx_above_200.eq(0)),
                ("breadth < 40%", day.breadth_ma20 < 40),
                ("breadth < 30%", day.breadth_ma20 < 30),
                ("volatility elevated", day.vol_high.eq(1))):
    eps = episodes(m)
    days = int(m.sum())
    print(f"\n{name}: {days} trading days in {len(eps)} episodes")
    for a, b in eps:
        n = int(m.loc[a:b].sum())
        print(f"    {a.date()} .. {b.date()}  ({n} days)")

print("\n" + "=" * 108)
print("THE SAME NUMBERS, ONE ROW PER EPISODE")
print("   if the edge lives in one episode, the average across trades is not evidence")
print("=" * 108)
V["pq"] = V.groupby(V.date.dt.to_period("Q"))["pwin"].transform(
    lambda s: pd.qcut(s, 5, labels=False, duplicates="drop") if s.notna().sum() > 50 else np.nan)
top = V[V.pq.eq(4)]
for name, col, thr in (("breadth < 30%", "breadth_ma20", 30),
                       ("breadth < 40%", "breadth_ma20", 40),
                       ("index below 200 DMA", "idx_above_200", 0.5)):
    m = (day[col] < thr)
    eps = episodes(m)
    print(f"\n{name}")
    rows = []
    for a, b in eps:
        g = top[(top.date >= a) & (top.date <= b)]
        gp = V[(V.date >= a) & (V.date <= b)]
        if len(gp) < 50: continue
        rows.append({"episode": f"{a.date()} .. {b.date()}",
                     "pool n": len(gp), "pool avgR": round(gp.R.mean(), 3),
                     "top-fifth n": len(g),
                     "top-fifth avgR": round(g.R.mean(), 3) if len(g) > 30 else np.nan,
                     "top-fifth win%": round(100 * (g.p > 0).mean(), 1) if len(g) > 30 else np.nan})
    print(pd.DataFrame(rows).to_string(index=False) if rows else "   (no episode with enough trades)")

print("\n" + "=" * 108)
print("WHY THE TRADES LOOK GOOD: what happened to the market AFTER each episode")
print("=" * 108)
idx = R["idx"].dropna()
for name, m in (("breadth < 30%", day.breadth_ma20 < 30),
                ("index below 200 DMA", day.idx_above_200.eq(0))):
    print(f"\n{name}")
    for a, b in episodes(m):
        fwd = idx.loc[b:]
        if len(fwd) < 61: 
            print(f"    {a.date()} .. {b.date()}   (not enough forward data)"); continue
        print(f"    ended {b.date()}: index +{100*(fwd.iloc[60]/fwd.iloc[0]-1):.1f}% over the next 60 trading days")
