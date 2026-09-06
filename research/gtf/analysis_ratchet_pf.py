"""A ratchet shortens the hold. When slots are the binding constraint, faster
turnover can pay for a worse trade. This tests that directly."""
import numpy as np, pandas as pd, sqlite3
pd.set_option("display.width", 240)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"

ev = pd.read_parquet("/tmp/gtf/ratchet7.parquet"); ev["date"] = pd.to_datetime(ev["date"])
con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt,symbol,close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()
mk = pd.DataFrame({"mkt": idx})
mk["v20"] = mk.mkt.pct_change().rolling(20).std()*np.sqrt(252)*100
mk["hv"] = (mk.v20 > mk.v20.rolling(500, min_periods=120).median()).astype(int)
ev = ev.merge(mk[["hv"]], left_on="date", right_index=True, how="left")
ev = ev[ev.hv.eq(1)]           # the volatility gate, as in the shipped config
print(f"{len(ev)} trades after the high-volatility gate\n")

SCHED = [c[2:] for c in ev.columns if c.startswith("p_")]

def run(e, pcol, bcol, cal, slots, seed=0, risk=0.015, start=1e6):
    e = e.dropna(subset=[pcol, bcol]).sort_values("date").copy()
    dmap = {v: i for i, v in enumerate(cal)}
    e["di"] = e.date.map(dmap); e = e[e.di.notna()]; e["di"] = e.di.astype(int)
    e["xd"] = e.di + e[bcol].astype(int)
    rng = np.random.default_rng(seed); e = e.assign(_o=rng.random(len(e)))
    by = {k: v for k, v in e.groupby("di")}
    eq = start; op = []; held = set(); curve = []; taken = 0
    for i, day in enumerate(cal):
        for p in [p for p in op if p[0] <= i]:
            eq += p[1]; op.remove(p); held.discard(p[2])
        t_ = by.get(i)
        if t_ is not None:
            gross = sum(p[3] for p in op)
            for _, r in t_.sort_values("_o").iterrows():
                if len(op) >= slots or r.symbol in held: continue
                sd = 2.0*r.atr_at_entry/r.entry_plan
                if not np.isfinite(sd) or sd <= 0: continue
                n_ = min(eq*risk/sd, eq/slots)
                if gross + n_ > eq: continue
                gross += n_
                op.append((int(r.xd), n_*r[pcol]/100.0, r.symbol, n_)); held.add(r.symbol); taken += 1
        curve.append((day, eq + sum(p[1] for p in op)))
    cv = pd.Series(dict(curve)).sort_index()
    yrs = (cv.index[-1]-cv.index[0]).days/365.25
    rr = cv.pct_change().dropna()
    return dict(total=100*(cv.iloc[-1]/start-1), cagr=100*((cv.iloc[-1]/start)**(1/yrs)-1),
                dd=100*(cv/cv.cummax()-1).min(),
                sharpe=rr.mean()/rr.std()*np.sqrt(252) if rr.std()>0 else np.nan, taken=taken)

for nm, lo, hi in (("LAST 2 YEARS", "2024-09-04", "2026-09-04"),
                   ("FULL WINDOW", "2021-04-12", "2026-09-04")):
    cal = np.sort(wide.index[(wide.index >= lo) & (wide.index <= hi)].unique().values)
    s = ev[(ev.date >= lo) & (ev.date <= hi)]
    print("=" * 132)
    print(f"{nm} — 15 slots, unlevered, median of 6 selection orders")
    print("=" * 132)
    rows = []
    for k in SCHED:
        r = [run(s, "p_"+k, "b_"+k, cal, 15, seed=q) for q in range(6)]
        rows.append({"schedule": k,
                     "avg% per trade": round(np.nanmean(s["p_"+k]), 2),
                     "med bars": int(np.nanmedian(s["b_"+k])),
                     "taken": int(np.median([q["taken"] for q in r])),
                     "total%": round(np.median([q["total"] for q in r]), 1),
                     "CAGR%": round(np.median([q["cagr"] for q in r]), 1),
                     "maxDD%": round(np.median([q["dd"] for q in r]), 1),
                     "Sharpe": round(np.median([q["sharpe"] for q in r]), 2)})
    t = pd.DataFrame(rows).sort_values("total%", ascending=False)
    print(t.to_string(index=False))
    sl = idx.loc[cal[0]:cal[-1]]; yrs = (sl.index[-1]-sl.index[0]).days/365.25
    rr = sl.pct_change().dropna()
    print(f"  benchmark: total {100*(sl.iloc[-1]/sl.iloc[0]-1):+.1f}%  "
          f"CAGR {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):+.1f}%  "
          f"maxDD {100*(sl/sl.cummax()-1).min():.1f}%  Sharpe {rr.mean()/rr.std()*np.sqrt(252):.2f}\n")
