"""S4 and GTF-7/7 together. Do they complement each other?"""
import numpy as np, pandas as pd, sqlite3
pd.set_option("display.width", 240)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"

s = pd.read_parquet("/tmp/gtf/s1s4_exits.parquet")
s["date"] = pd.to_datetime(s["entry_date"])
s4 = s[s.strategy.eq("S4") & s.p_new.notna()].copy()
s4 = s4.rename(columns={"ticker": "symbol", "p_new": "p", "b_new": "b", "entry": "entry_plan"})
s4["src"] = "S4"

g = pd.read_parquet("/tmp/gtf/ratchet7.parquet"); g["date"] = pd.to_datetime(g["date"])
gcol = "p_breakeven only at +15%"; bcol = "b_breakeven only at +15%"
g = g.rename(columns={gcol: "p", bcol: "b"})
g["src"] = "GTF"

con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt,symbol,close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()
mk = pd.DataFrame({"mkt": idx})
mk["v20"] = mk.mkt.pct_change().rolling(20).std()*np.sqrt(252)*100
mk["hv"] = (mk.v20 > mk.v20.rolling(500, min_periods=120).median()).astype(int)
g = g.merge(mk[["hv"]], left_on="date", right_index=True, how="left")
g = g[g.hv.eq(1) & g.turnover_cr.ge(10)]

K = ["symbol", "date", "entry_plan", "atr_at_entry", "p", "b", "src"]
both = pd.concat([s4[K], g[K]], ignore_index=True)
print(f"S4 {len(s4)}   GTF 7/7 {len(g)}   combined {len(both)}")
print("\ncorrelation of the two return streams by month:")
mo = both.assign(m=both.date.dt.to_period("M")).pivot_table(index="m", columns="src",
                                                            values="p", aggfunc="mean")
print(f"  {mo.corr().iloc[0,1]:+.3f}   (months both active: {mo.dropna().shape[0]})")

def run(e, cal, slots=15, seed=0, risk=0.015, start=1e6):
    e = e.dropna(subset=["p", "b"]).sort_values("date").copy()
    dmap = {v: i for i, v in enumerate(cal)}
    e["di"] = e.date.map(dmap); e = e[e.di.notna()]; e["di"] = e.di.astype(int)
    e["xd"] = e.di + e.b.astype(int)
    rng = np.random.default_rng(seed); e = e.assign(_o=rng.random(len(e)))
    by = {k: v for k, v in e.groupby("di")}
    eq = start; op = []; held = set(); curve = []; taken = 0
    for i, day in enumerate(cal):
        for p_ in [p_ for p_ in op if p_[0] <= i]:
            eq += p_[1]; op.remove(p_); held.discard(p_[2])
        t_ = by.get(i)
        if t_ is not None:
            gross = sum(p_[3] for p_ in op)
            for _, r in t_.sort_values("_o").iterrows():
                if len(op) >= slots or r.symbol in held: continue
                sd = 2.0*r.atr_at_entry/r.entry_plan
                if not np.isfinite(sd) or sd <= 0: continue
                n_ = min(eq*risk/sd, eq/slots)
                if gross + n_ > eq: continue
                gross += n_
                op.append((int(r.xd), n_*r.p/100.0, r.symbol, n_)); held.add(r.symbol); taken += 1
        curve.append((day, eq + sum(p_[1] for p_ in op)))
    cv = pd.Series(dict(curve)).sort_index()
    yrs = (cv.index[-1]-cv.index[0]).days/365.25
    rr = cv.pct_change().dropna()
    return dict(total=100*(cv.iloc[-1]/start-1), cagr=100*((cv.iloc[-1]/start)**(1/yrs)-1),
                dd=100*(cv/cv.cummax()-1).min(),
                sharpe=rr.mean()/rr.std()*np.sqrt(252) if rr.std()>0 else np.nan, taken=taken)

for nm, lo, hi in (("LAST 2 YEARS", "2024-09-04", "2026-09-04"),
                   ("FULL WINDOW", "2021-06-01", "2026-09-04")):
    cal = np.sort(wide.index[(wide.index >= lo) & (wide.index <= hi)].unique().values)
    print("\n" + "=" * 110)
    print(f"{nm} — 15 slots, unlevered, median of 6 selection orders")
    print("=" * 110)
    rows = []
    for k, ev in (("S4 only", s4[K]), ("GTF 7/7 only", g[K]), ("S4 + GTF together", both)):
        e = ev[(ev.date >= lo) & (ev.date <= hi)]
        if len(e) < 20: continue
        r = [run(e, cal, seed=q) for q in range(6)]
        rows.append({"system": k, "signals": len(e),
                     "avg% per trade": round(e.p.mean(), 2),
                     "taken": int(np.median([q["taken"] for q in r])),
                     "total%": round(np.median([q["total"] for q in r]), 1),
                     "CAGR%": round(np.median([q["cagr"] for q in r]), 1),
                     "maxDD%": round(np.median([q["dd"] for q in r]), 1),
                     "Sharpe": round(np.median([q["sharpe"] for q in r]), 2)})
    print(pd.DataFrame(rows).to_string(index=False))
    sl = idx.loc[cal[0]:cal[-1]]; yrs = (sl.index[-1]-sl.index[0]).days/365.25
    rr = sl.pct_change().dropna()
    print(f"  benchmark: total {100*(sl.iloc[-1]/sl.iloc[0]-1):+.1f}%  "
          f"CAGR {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):+.1f}%  "
          f"maxDD {100*(sl/sl.cummax()-1).min():.1f}%  Sharpe {rr.mean()/rr.std()*np.sqrt(252):.2f}")
