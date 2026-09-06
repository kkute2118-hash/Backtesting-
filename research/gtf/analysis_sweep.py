"""Does the liquidity sweep work, standalone and as a filter?"""
import numpy as np, pandas as pd, sqlite3
pd.set_option("display.width", 240)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"

d = pd.read_parquet("/tmp/gtf/sweep.parquet"); d["date"] = pd.to_datetime(d["date"])
print(f"{len(d)} setups, {d.symbol.nunique()} symbols, {d.date.min().date()} .. {d.date.max().date()}\n")

def st(x, label):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 20: return {"set": label, "n": len(x)}
    w = x[x > 0]; l = x[x <= 0]
    return {"set": label, "n": len(x), "win%": round(100*len(w)/len(x), 1),
            "avg%": round(x.mean(), 2), "PF": round(w.sum()/-l.sum(), 2) if l.sum() < 0 else np.inf,
            "avg win": round(w.mean(), 1) if len(w) else np.nan,
            "avg loss": round(l.mean(), 1) if len(l) else np.nan}

print("=" * 104)
print("STANDALONE, both exits")
print("=" * 104)
rows = []
for nm, m in (("full window", pd.Series(True, index=d.index)),
              ("last 2 years", d.date >= "2024-09-04")):
    for col, lab in (("p_8atr", "2ATR stop / 8ATR target"), ("p_be15", "2ATR stop / breakeven +15%")):
        rows.append({**st(d.loc[m, col], f"{nm} — {lab}")})
print(pd.DataFrame(rows).to_string(index=False))

# benchmarks already established, same exit, same machinery
g = pd.read_parquet("/tmp/gtf/ratchet7.parquet"); g["date"] = pd.to_datetime(g["date"])
print("\nfor comparison, on the same exit (breakeven +15%):")
print(" ", st(g["p_breakeven only at +15%"], "GTF 7/7 (all, no gates)"))
s4 = pd.read_parquet("/tmp/gtf/s1s4_exits.parquet")
s4["date"] = pd.to_datetime(s4["entry_date"])
print(" ", st(s4.loc[s4.strategy.eq("S4"), "p_be15"], "S4"))
print(" ", st(s4["p_be15"], "S1-S4 all signals"))

print("\n" + "=" * 104)
print("BY YEAR (breakeven +15% exit)")
print("=" * 104)
gy = d.set_index("date").groupby(pd.Grouper(freq="YE"))["p_be15"]
print(pd.DataFrame({"n": gy.size(), "win%": gy.apply(lambda s: 100*(s>0).mean()),
                    "avg%": gy.mean()}).round(2).to_string())

print("\n" + "=" * 104)
print("WHICH PART OF THE SETUP IS DOING THE WORK?")
print("=" * 104)
for f, bins in (("reclaim_bars", [-1, 0, 1, 2, 3]),
                ("reclaim_relvol", [0, 1.2, 1.5, 2.0, 3.0, 99]),
                ("sweep_depth_atr", [0, 0.25, 0.5, 1.0, 2.0, 99]),
                ("weekly_slope_pct", [-99, 0, 2, 5, 10, 999]),
                ("retest_bars", [0, 2, 5, 10, 16]),
                ("above_swing_pct", [-99, 2, 5, 10, 20, 999]),
                ("dist_ema200_atr", [-99, -2, 0, 2, 5, 999]),
                ("atr_pct", [0, 2, 3, 4, 6, 99])):
    b = pd.cut(d[f], bins)
    g2 = d.groupby(b, observed=True)["p_be15"].agg(["size", "mean"])
    g2 = g2[g2["size"] >= 60]
    if len(g2) >= 2:
        line = "  ".join(f"{str(i):>14}: {r['mean']:+5.2f}% (n={int(r['size'])})"
                         for i, r in g2.iterrows())
        print(f"{f:<18} {line}")

print("\n" + "=" * 104)
print("AS A FILTER — do S1-S4 or GTF signals near a recent sweep do better?")
print("=" * 104)
# a signal is 'sweep-confirmed' if the same symbol had a sweep reclaim in the last N bars
sw = d[["symbol", "reclaim_bar", "date"]].copy()
def tag(sig, barcol, symcol, window=20):
    key = {}
    for s_, grp in d.groupby("symbol"):
        key[s_] = np.sort(grp.reclaim_bar.to_numpy())
    out = np.zeros(len(sig), dtype=bool)
    for i, (s_, b_) in enumerate(zip(sig[symcol].to_numpy(), sig[barcol].to_numpy())):
        arr = key.get(s_)
        if arr is None or not np.isfinite(b_): continue
        j = np.searchsorted(arr, b_, side="right") - 1
        if j >= 0 and 0 <= b_ - arr[j] <= window:
            out[i] = True
    return out

g["swept"] = tag(g, "bar", "symbol")
print("\nGTF 7/7 signals, split by whether a sweep-reclaim happened in the prior 20 bars:")
for v, lab in ((True, "after a sweep"), (False, "no sweep")):
    print(" ", st(g.loc[g.swept.eq(v), "p_breakeven only at +15%"], lab))
