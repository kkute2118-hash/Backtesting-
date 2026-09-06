"""The capacity fix.

FINDINGS_V2 section 10: slots fill on the way down through a cluster with the
early, poor trades, and the good ones arrive with nothing left. That is an
allocation problem, not a signal problem. This tests ways of not spending the
whole book on day one of a selloff.
"""
import numpy as np, pandas as pd, sqlite3
pd.set_option("display.width", 250)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"
PCOL, BCOL = "p_breakeven only at +15%", "b_breakeven only at +15%"

ev = pd.read_parquet("/tmp/gtf/ratchet7.parquet"); ev["date"] = pd.to_datetime(ev["date"])
con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt,symbol,close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()
mk = pd.DataFrame({"mkt": idx})
mk["v20"] = mk.mkt.pct_change().rolling(20).std()*np.sqrt(252)*100
mk["hv"] = (mk.v20 > mk.v20.rolling(500, min_periods=120).median()).astype(int)
mk["ma20"] = mk.mkt.rolling(20).mean()
mk["above20"] = (mk.mkt > mk.ma20).astype(int)          # index not in freefall
ev = ev.merge(mk[["hv", "above20"]], left_on="date", right_index=True, how="left")
ev = ev[ev.hv.eq(1)].copy()
print(f"{len(ev)} 7/7 trades after the volatility gate\n")

def run(e, cal, slots=15, seed=0, risk=0.015, start=1e6,
        rank=None, max_new_per_day=None, reserve=1.0, need_above20=False):
    e = e.dropna(subset=[PCOL, BCOL]).sort_values("date").copy()
    if need_above20:
        e = e[e.above20.eq(1)]
    dmap = {v: i for i, v in enumerate(cal)}
    e["di"] = e.date.map(dmap); e = e[e.di.notna()]; e["di"] = e.di.astype(int)
    e["xd"] = e.di + e[BCOL].astype(int)
    rng = np.random.default_rng(seed); e = e.assign(_o=rng.random(len(e)))
    by = {k: v for k, v in e.groupby("di")}
    eq = start; op = []; held = set(); curve = []; taken = []
    for i, day in enumerate(cal):
        for p in [p for p in op if p[0] <= i]:
            eq += p[1]; op.remove(p); held.discard(p[2])
        t_ = by.get(i)
        if t_ is not None:
            gross = sum(p[3] for p in op)
            order = t_.sort_values(rank, ascending=False) if rank else t_.sort_values("_o")
            new_today = 0
            for _, r in order.iterrows():
                if len(op) >= slots or r.symbol in held:
                    continue
                if max_new_per_day is not None and new_today >= max_new_per_day:
                    break
                sd = 2.0*r.atr_at_entry/r.entry_plan
                if not np.isfinite(sd) or sd <= 0: continue
                n_ = min(eq*risk/sd, eq/slots)
                if gross + n_ > eq * reserve:     # keep dry powder
                    continue
                gross += n_; new_today += 1
                op.append((int(r.xd), n_*r[PCOL]/100.0, r.symbol, n_))
                held.add(r.symbol); taken.append(r[PCOL])
        curve.append((day, eq + sum(p[1] for p in op)))
    cv = pd.Series(dict(curve)).sort_index()
    yrs = (cv.index[-1]-cv.index[0]).days/365.25
    rr = cv.pct_change().dropna()
    return dict(total=100*(cv.iloc[-1]/start-1), cagr=100*((cv.iloc[-1]/start)**(1/yrs)-1),
                dd=100*(cv/cv.cummax()-1).min(),
                sharpe=rr.mean()/rr.std()*np.sqrt(252) if rr.std()>0 else np.nan,
                taken=len(taken), avgt=float(np.mean(taken)) if taken else np.nan)

POLICIES = {
    "A first come (current)":            dict(),
    "B rank by zone width":              dict(rank="zone_h_pct"),
    "C rank by leg-out achievement":     dict(rank="legout_atr"),
    "D rank by ATR%":                    dict(rank="atr_pct"),
    "E max 2 new positions per day":     dict(max_new_per_day=2),
    "F max 3 new per day":               dict(max_new_per_day=3),
    "G max 5 new per day":               dict(max_new_per_day=5),
    "H keep 40% dry powder":             dict(reserve=0.60),
    "I keep 25% dry powder":             dict(reserve=0.75),
    "J index above its 20d MA":          dict(need_above20=True),
    "K max 3/day + 25% dry":             dict(max_new_per_day=3, reserve=0.75),
    "L max 3/day + rank by width":       dict(max_new_per_day=3, rank="zone_h_pct"),
    "M max 2/day + index above 20d MA":  dict(max_new_per_day=2, need_above20=True),
}

for nm, lo, hi in (("LAST 2 YEARS", "2024-09-04", "2026-09-04"),
                   ("FULL WINDOW", "2021-04-12", "2026-09-04")):
    cal = np.sort(wide.index[(wide.index >= lo) & (wide.index <= hi)].unique().values)
    s = ev[(ev.date >= lo) & (ev.date <= hi)]
    print("=" * 126)
    print(f"{nm} — allocation policies, 15 slots, breakeven-at-+15% exit, median of 6 orders")
    print("=" * 126)
    rows = []
    for k, kw in POLICIES.items():
        r = [run(s, cal, seed=q, **kw) for q in range(6)]
        rows.append({"policy": k,
                     "taken": int(np.median([q["taken"] for q in r])),
                     "avg% taken": round(np.median([q["avgt"] for q in r]), 2),
                     "total%": round(np.median([q["total"] for q in r]), 1),
                     "CAGR%": round(np.median([q["cagr"] for q in r]), 1),
                     "maxDD%": round(np.median([q["dd"] for q in r]), 1),
                     "Sharpe": round(np.median([q["sharpe"] for q in r]), 2)})
    print(pd.DataFrame(rows).sort_values("total%", ascending=False).to_string(index=False))
    sl = idx.loc[cal[0]:cal[-1]]; yrs = (sl.index[-1]-sl.index[0]).days/365.25
    rr = sl.pct_change().dropna()
    print(f"  benchmark: total {100*(sl.iloc[-1]/sl.iloc[0]-1):+.1f}%  "
          f"CAGR {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):+.1f}%  Sharpe {rr.mean()/rr.std()*np.sqrt(252):.2f}\n")
