"""Two questions, tested separately.

  A. INDEX TIMING. Does it pay to only signal when the Nifty is near its own
     20/50 EMA, or near support? This is different from the regime test that
     failed earlier: that one asked whether the market should be STRONG, this
     asks whether it should be PULLED BACK. A shallow index pullback is not
     the same thing as a breadth collapse.

  B. VOLUME. Six new volume features, each measuring something different:
     today against normal, whether volume is drying up into the pullback or
     being dumped, whether the base of volume is rising, how much of the month
     traded on up days, effort against result, and the largest recent spike.
"""
import numpy as np, pandas as pd
import rank as RK
pd.set_option("display.width", 250)
CUT = pd.Timestamp("2024-09-04")

d = RK.prepare()
d = d[d.turnover_cr >= 25].copy()
print(f"{len(d)} candidates, {d.date.min().date()} .. {d.date.max().date()}")
print(f"volume features present: {[c for c in RK.VOL_FEATS if c in d.columns]}")
print(f"index features present:  {[c for c in RK.IDX_FEATS if c in d.columns]}\n")


def band(g, col, bins, target="R"):
    b = pd.cut(g[col], bins)
    t = g.groupby(b, observed=True).agg(n=(target, "size"), avgR=(target, "mean"),
                                        win=("p", lambda s: 100 * (s > 0).mean()))
    return t[t["n"] >= 300]


print("=" * 104)
print("A. INDEX TIMING - where was the Nifty when the signal fired?")
print("=" * 104)
for col, bins, lab in (
        ("idx_from_ema20_sd", [-99, -2, -1, 0, 1, 2, 99], "index vs its 20 EMA (in index SDs)"),
        ("idx_from_ema50_sd", [-99, -2, -1, 0, 1, 2, 99], "index vs its 50 EMA (in index SDs)"),
        ("idx_above_60d_low", [0, 2, 5, 10, 15, 99], "index % above its 60-day low")):
    print(f"\n{lab}")
    for period, g in (("full window", d), ("last 2 years", d[d.date >= CUT])):
        t = band(g, col, bins)
        if len(t) < 2: continue
        print(f"  {period:<14} " + "  ".join(
            f"{str(i):>12}: {r.avgR:+6.3f}R ({r.win:4.1f}%, n={int(r.n)})"
            for i, r in t.iterrows()))

print("\n" + "=" * 104)
print("B. VOLUME - does any of it separate winners from losers?")
print("=" * 104)
for col, bins in (("relvol50", [0, 0.7, 1.0, 1.5, 2.5, 99]),
                  ("vol_dryup", [0, 0.7, 0.9, 1.1, 1.5, 99]),
                  ("vol_trend", [0, 0.8, 1.0, 1.2, 1.6, 99]),
                  ("up_vol_share", [0, 40, 45, 50, 55, 100]),
                  ("max_relvol_20", [0, 2, 3, 5, 10, 999]),
                  ("vol_per_move", [0, 0.3, 0.6, 1.0, 2.0, 999])):
    if col not in d.columns: continue
    print(f"\n{col}")
    for period, g in (("full window", d), ("last 2 years", d[d.date >= CUT])):
        t = band(g, col, bins)
        if len(t) < 2: continue
        print(f"  {period:<14} " + "  ".join(
            f"{str(i):>12}: {r.avgR:+6.3f}R ({r.win:4.1f}%, n={int(r.n)})"
            for i, r in t.iterrows()))
