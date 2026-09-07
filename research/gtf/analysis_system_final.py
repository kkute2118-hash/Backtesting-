"""The complete system, measured, with and without the breadth tilt.

The tilt: take more trades a week when market breadth is low. The evidence for
it is directionally consistent but thin - two scored episodes at breadth under
30% (+0.386 and +1.482 R for the marked picks) and three at index-below-200
(+2.303, +0.106, +0.202). Every one positive, none of them independent of the
bounce that followed. So it is tested here as a modest TILT in position count,
never as an on/off switch, and it is reported separately so it can be dropped
without touching the rest of the system.
"""
import numpy as np, pandas as pd, sqlite3
import portfolio as PF
pd.set_option("display.width", 250)
DB = ("/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c"
      "/scratchpad/data/market_data.sqlite3")
CUT = pd.Timestamp("2024-09-04")

con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt, symbol, close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
CAL = np.sort(wide.index.unique().values); DMAP = {v: i for i, v in enumerate(CAL)}
NDAYS = len(CAL)
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()

V = pd.read_parquet("/tmp/gtf/pool_pwin.parquet"); V["date"] = pd.to_datetime(V["date"])
R = pd.read_parquet("/tmp/gtf/regime.parquet")
V = V.join(R[["breadth_ma20", "idx_above_200"]], on="date").sort_values("date")
V = V.reset_index(drop=True)
DI = V.date.factorize()[0]
WK = V.date.dt.to_period("W").astype(str).to_numpy()
SY = V.symbol.to_numpy()
BR = V.breadth_ma20.to_numpy()


def pick_idx(key, base=2, tilt=None):
    """Weekly budget by mark. `tilt` raises the budget when breadth is low."""
    order = np.lexsort((-key, DI))
    spent = {}; keep = []
    n = len(order); i = 0
    while i < n:
        j = i; day = DI[order[i]]
        while j < n and DI[order[j]] == day:
            j += 1
        k0 = order[i]
        budget = base
        if tilt is not None and np.isfinite(BR[k0]):
            budget = tilt(BR[k0])
        wk = WK[k0]; used = spent.get(wk, 0)
        if used < budget:
            seen = set()
            for k in order[i:j]:
                if used >= budget:
                    break
                if SY[k] in seen:
                    continue
                seen.add(SY[k]); keep.append(k); used += 1
            spent[wk] = used
        i = j
    return np.array(keep, dtype=int)


def tilt_rule(b):
    """Modest, three-step, round thresholds. Not a fitted curve."""
    if b < 30: return 4
    if b < 40: return 3
    return 2


CONFIGS = {
    "base: 2 a week, marked": lambda: pick_idx(V.pwin.to_numpy(), base=2),
    "3 a week, marked": lambda: pick_idx(V.pwin.to_numpy(), base=3),
    "breadth tilt (2/3/4)": lambda: pick_idx(V.pwin.to_numpy(), base=2, tilt=tilt_rule),
    "random, 2 a week": lambda: pick_idx(np.random.default_rng(7).random(len(V)), base=2),
}

print("=" * 132)
print("THE SYSTEM, END TO END.  Rs 10,00,000, 1% risk, no leverage,")
print("median of 40 selection orderings.  Costs 0.23% a round trip are already in every trade.")
print("=" * 132)
rows = []
for name, f in CONFIGS.items():
    sel = V.iloc[f()]
    for lab, cut in (("full window", None), ("last 2 years", CUT)):
        sub = sel if cut is None else sel[sel.date >= cut]
        yrs = (sub.date.max() - sub.date.min()).days / 365.25
        r = PF.summary(PF.arrays(sub, DMAP, NDAYS), CAL, seeds=40, years=yrs)
        if not r: continue
        rows.append({"system": name, "period": lab, "signals": len(sub),
                     "trades": r["trades"], "ROI%": r["ROI%"], "CAGR%": r["CAGR%"],
                     "maxDD%": r["maxDD%"], "Sharpe": r["Sharpe"],
                     "10-90 pct": f"[{r['worst']:.0f}, {r['best']:.0f}]",
                     "win%": round(100 * (sub.p > 0).mean(), 1),
                     "avgR": round(sub.R.mean(), 3)})
t = pd.DataFrame(rows)
print(t.sort_values(["period", "system"]).to_string(index=False))

print("\nbenchmark, same spans:")
for lab, sl in (("full window", idx.loc[V.date.min():]), ("last 2 years", idx.loc[CUT:])):
    yrs = (sl.index[-1] - sl.index[0]).days / 365.25
    dd = 100 * (sl / sl.cummax() - 1).min()
    print(f"  equal-weight index, {lab:<13} ROI {100*(sl.iloc[-1]/sl.iloc[0]-1):+7.1f}%   "
          f"CAGR {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):+5.1f}%   maxDD {dd:.1f}%")

print("\n" + "=" * 132)
print("YEAR BY YEAR - base system, one ordering, so the shape is visible")
print("=" * 132)
sel = V.iloc[CONFIGS["base: 2 a week, marked"]()]
roi, cv, taken = PF.run(PF.arrays(sel, DMAP, NDAYS), seed=0, curve=True)
cv.index = [CAL[i] for i in cv.index]
cv = pd.Series(cv.values, index=pd.to_datetime(cv.index))
yr = cv.resample("YE").last()
prev = 1_000_000.0
for d, v in yr.items():
    print(f"  {d.year}:  Rs {v:>12,.0f}   ({100*(v/prev-1):+6.1f}% that year)")
    prev = v
