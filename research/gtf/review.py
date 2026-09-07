"""Your weekly review list: three names, ranked, with what to check on each.

WHY THREE AND NOT TWENTY

You asked for the smallest possible list of the best names. The data is blunt
about how small. Taking the top 2 marks each week returned +10.7% over the
last two years. Handing yourself a 5-name list and choosing 2 from it returned
+0.5% if the choice is no better than a coin toss, and an 8-name list -0.1%.
The ranking's value is concentrated in the very top of the list; every name
added below dilutes it.

The cost of overriding is measurable too. Skipping the top-ranked name and
taking the next two instead: +10.7% becomes -1.7%. One veto costs about
twelve points of annual return.

SO USE YOUR EYES FOR WHAT THE MODEL CANNOT SEE, NOT TO RE-RANK

The model reads price and volume. It does not know about earnings tomorrow,
a pending merger, a stock split the data never adjusted for, a regulatory
action, or a price series that is simply wrong. Those are real reasons to
skip a name, and the model will never catch them.

It DOES already know the chart is choppy, the stock is extended, volatility
is high, the trend is weak - volatility and distance from the 200 EMA were
the two strongest features in the permutation test. Vetoing on those is
overriding the model with the same information it already used, and the
substitution cost above is what that habit costs.

Rule of thumb: skip a name only if you can name the fact, and the fact is not
on the chart.
"""
from __future__ import annotations
import sys
import numpy as np, pandas as pd
import system as SYS

SHORTLIST = 3


def build(asof=None, equity=1_000_000.0):
    out, breadth, n, asof = SYS.run(asof, equity)
    return out, breadth, n, asof


def notes(r):
    """What is unusual about this candidate, in plain terms."""
    out = []
    if r.stop_pct > 10:
        out.append(f"wide stop ({r.stop_pct:.0f}%) - small position")
    if r.turnover_cr < 40:
        out.append(f"thinner ({r.turnover_cr:.0f} Cr/day) - check you can exit")
    if r.dist_ema200_atr < 0:
        out.append("below its 200 EMA")
    elif r.dist_ema200_atr > 3:
        out.append("extended above its 200 EMA")
    if r.rsi14 < 35:
        out.append(f"weak (RSI {r.rsi14:.0f})")
    if r.ret_120d < 0:
        out.append(f"6-month laggard ({r.ret_120d:+.0f}%)")
    return "; ".join(out) if out else "nothing unusual"


if __name__ == "__main__":
    asof = sys.argv[1] if len(sys.argv) > 1 else None
    eq = float(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000.0
    # ask the system for a longer list than it would trade, then show ranks
    import rank as RK, regime as RG
    pool = RK.prepare()
    pool = pool[pool.turnover_cr >= SYS.FLOOR_CR]
    asof = pd.Timestamp(asof) if asof else pool.date.max()
    reg = RG.build(SYS.DB); reg = reg[reg.index <= asof]
    breadth = float(reg.breadth_ma20.iloc[-1]) if len(reg) else np.nan
    take = SYS.budget(breadth)

    m, feats, ref = SYS.fit_mark(pool, asof)
    live = pool[pool.date == asof].copy()
    if not len(live):
        print(f"\nas of {asof.date()}: nothing fired today.\n"); raise SystemExit
    live["pwin"] = m.predict_proba(live[feats].to_numpy())[:, 1]
    live["mark"] = [100 * (ref < v).mean() for v in live.pwin]
    live = live.sort_values("mark", ascending=False).drop_duplicates("symbol").head(SHORTLIST)
    live["stop"] = live.entry - SYS.STOP_ATR * live.entry * live.atr_pct / 100
    live["stop_pct"] = 100 * (live.entry - live.stop) / live.entry
    risk = eq * SYS.RISK_PCT / 100
    live["shares"] = np.minimum(risk / (live.entry - live.stop),
                                eq * SYS.MAX_POSITION_PCT / 100 / live.entry).astype(int)

    print(f"\nas of {asof.date()}   capital Rs {eq:,.0f}   breadth {breadth:.0f}%"
          f"   -> TAKE THE TOP {take} THIS WEEK\n")
    for i, (_, r) in enumerate(live.iterrows(), 1):
        flag = "TAKE" if i <= take else "reserve"
        print(f"  {i}. {r.symbol:<12} {flag:<8} mark {r.mark:5.1f}   from {r.source}")
        print(f"     entry {r.entry:>9.2f}   stop {r.stop:>9.2f} ({r.stop_pct:.1f}%)"
              f"   {r.shares} shares = Rs {r.shares*r.entry:,.0f}")
        print(f"     breakeven stop at {r.entry*1.15:.2f}   time exit after 60 days")
        print(f"     note: {notes(r)}")
        print()
    print("  Before taking: check earnings date, any corporate action, and that")
    print("  the price series looks sane. Those are the model's blind spots.")
    print("  Skip a name only if you can name a fact that is NOT on the chart -")
    print("  each veto has historically cost about 12 points of annual return.\n")
