"""Does sitting out bad regimes fix the long-only problem?

Pre-specified rules only - index above its 200-day, breadth above a round
threshold, volatility below its own past median, and the obvious pairs. No
threshold search: 40 and 50 percent breadth are chosen because they are the
round numbers either side of "half the market is in an uptrend", not because
they tested well.

Measured on the whole candidate pool first (does the regime predict whether
LONGS work at all?) and then on the marked picks (does it stack with the
ranking, or is it the same information twice?).
"""
import numpy as np, pandas as pd
pd.set_option("display.width", 240)
CUT = pd.Timestamp("2024-09-04")

V = pd.read_parquet("/tmp/gtf/pool_pwin.parquet")
V["date"] = pd.to_datetime(V["date"])
R = pd.read_parquet("/tmp/gtf/regime.parquet")
V = V.join(R, on="date")
print(f"{len(V)} candidates joined to regime, "
      f"{V.idx_above_200.notna().mean():.1%} have a regime reading\n")

RULES = {
    "no filter": lambda x: pd.Series(True, index=x.index),
    "index above its 200 DMA": lambda x: x.idx_above_200.eq(1),
    "breadth > 40%": lambda x: x.breadth_ma20 > 40,
    "breadth > 50%": lambda x: x.breadth_ma20 > 50,
    "volatility not elevated": lambda x: x.vol_high.eq(0),
    "index above 200 AND breadth > 40%": lambda x: x.idx_above_200.eq(1) & (x.breadth_ma20 > 40),
    "index above 200 AND breadth > 50%": lambda x: x.idx_above_200.eq(1) & (x.breadth_ma20 > 50),
    "breadth > 40% AND vol not elevated": lambda x: (x.breadth_ma20 > 40) & x.vol_high.eq(0),
}

print("=" * 120)
print("1. THE WHOLE POOL - does the regime say whether being long works?")
print("=" * 120)
rows = []
for name, f in RULES.items():
    m = f(V).fillna(False)
    g = V[m]
    if len(g) < 500: continue
    row = {"regime rule": name, "candidates": len(g),
           "share of days": f"{100*len(g)/len(V):.0f}%"}
    for lab, sub in (("2022-23", g[g.date < "2024-01-01"]),
                     ("2024+", g[g.date >= "2024-01-01"]),
                     ("last 2y", g[g.date >= CUT])):
        row[f"avgR {lab}"] = round(sub.R.mean(), 3) if len(sub) > 200 else np.nan
        row[f"win% {lab}"] = round(100 * (sub.p > 0).mean(), 1) if len(sub) > 200 else np.nan
    rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 120)
print("2. THE MARKED PICKS - top fifth by P(win), inside each regime")
print("=" * 120)
V["q"] = V.date.dt.to_period("Q")
V["pq"] = V.groupby("q")["pwin"].transform(
    lambda s: pd.qcut(s, 5, labels=False, duplicates="drop") if s.notna().sum() > 50 else np.nan)
top = V[V.pq.eq(4)]
rows = []
for name, f in RULES.items():
    m = f(top).fillna(False)
    g = top[m]
    if len(g) < 200: continue
    row = {"regime rule": name, "candidates": len(g)}
    for lab, sub in (("2022-23", g[g.date < "2024-01-01"]),
                     ("2024+", g[g.date >= "2024-01-01"]),
                     ("last 2y", g[g.date >= CUT])):
        row[f"avgR {lab}"] = round(sub.R.mean(), 3) if len(sub) > 100 else np.nan
        row[f"win% {lab}"] = round(100 * (sub.p > 0).mean(), 1) if len(sub) > 100 else np.nan
    rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 120)
print("3. WHAT IT COSTS: how much of the time is the market tradeable?")
print("=" * 120)
day = V.drop_duplicates("date").set_index("date").sort_index()
for name, f in RULES.items():
    m = f(day).fillna(False)
    yr = m.groupby(m.index.year).mean().mul(100).round(0).astype(int)
    print(f"  {name:<36} " + "  ".join(f"{y}:{v:>3}%" for y, v in yr.items()))


print("\n" + "=" * 120)
print("4. THE INVERSE. Every filter toward a STRONG market made things worse,")
print("   monotonically. These setups are dip-buys, so the reading may be that")
print("   the good entries happen when the market is frightened, not calm.")
print("   This test was suggested by the result above, so it gets its own")
print("   period splits rather than a single pooled number.")
print("=" * 120)
INV = {
    "index BELOW its 200 DMA": lambda x: x.idx_above_200.eq(0),
    "breadth < 40%": lambda x: x.breadth_ma20 < 40,
    "breadth < 30%": lambda x: x.breadth_ma20 < 30,
    "volatility elevated": lambda x: x.vol_high.eq(1),
    "breadth < 40% AND vol elevated": lambda x: (x.breadth_ma20 < 40) & x.vol_high.eq(1),
    "index below 200 AND vol elevated": lambda x: x.idx_above_200.eq(0) & x.vol_high.eq(1),
}
for title, frame in (("WHOLE POOL", V), ("TOP FIFTH BY P(win)", V[V.pq.eq(4)])):
    print(f"\n{title}")
    rows = []
    for name, f in {**{"no filter": lambda x: pd.Series(True, index=x.index)}, **INV}.items():
        m = f(frame).fillna(False)
        g = frame[m]
        if len(g) < 300: continue
        row = {"regime rule": name, "n": len(g)}
        for lab, sub in (("2022-23", g[g.date < "2024-01-01"]),
                         ("2024", g[(g.date >= "2024-01-01") & (g.date < "2025-01-01")]),
                         ("2025+", g[g.date >= "2025-01-01"]),
                         ("last 2y", g[g.date >= CUT])):
            row[f"avgR {lab}"] = round(sub.R.mean(), 3) if len(sub) > 150 else np.nan
        row["win% last2y"] = round(100 * (g[g.date >= CUT].p > 0).mean(), 1) \
            if (g.date >= CUT).sum() > 150 else np.nan
        rows.append(row)
    print(pd.DataFrame(rows).to_string(index=False))
