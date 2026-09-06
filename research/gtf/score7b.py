"""Why 7/7 looks different now, and what it is worth combined."""
import numpy as np, pandas as pd, sqlite3
pd.set_option("display.width", 220)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"
d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
xx = pd.read_parquet("/tmp/gtf/exits.parquet")
d = pd.concat([d, xx[[c for c in xx.columns if c[:2] in ("x_", "b_")]]], axis=1)
d = d[(d.gap_through == 0)].copy()
import evaluate as E
d["r_distal2R"] = E.r_of(d, "R", 2.0)          # old scoring: distal stop, 2R target

print("=" * 100)
print("WHY THE SCORE FLIPPED: it was the STOP, not the score")
print("=" * 100)
t = d.groupby("score").agg(
    n=("score", "size"),
    old_avgR_distal_stop=("r_distal2R", "mean"),
    new_avg_pct_atr_stop=("x_fix_2_8", "mean"),
    median_zone_width_pct=("risk_pct", "median")).round(3)
print(t.to_string())
print("""
Reading down the two middle columns: with the video's own distal stop the score
is inversely predictive, exactly as reported earlier. With a 2 ATR stop the
inversion disappears and 7/7 becomes the best bucket.

The mechanism is the same one from FINDINGS section 2: a 7/7 zone is by
construction among the thinnest (median width 2.19% against 5.19% at score 1), so a
stop at its distal line sits inside the noise. That penalty was never a
statement about zone quality - it was a statement about where the stop was.
Move the stop off the zone and the score's real content shows through.""")

con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt,symbol,close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()
mk = pd.DataFrame({"mkt": idx})
mk["v20"] = mk.mkt.pct_change().rolling(20).std()*np.sqrt(252)*100
mk["hv"] = (mk.v20 > mk.v20.rolling(500, min_periods=120).median()).astype(int)
d = d.merge(mk[["hv"]], left_on="date", right_index=True, how="left")
d = d[d["x_fix_2_8"].notna()]

def run(ev, cal, slots, seed=0, risk=0.015, start=1e6):
    ev = ev.dropna(subset=["x_fix_2_8", "b_fix_2_8"]).sort_values("date").copy()
    dmap = {v: i for i, v in enumerate(cal)}
    ev["di"] = ev.date.map(dmap); ev = ev[ev.di.notna()]; ev["di"] = ev.di.astype(int)
    ev["xd"] = ev.di + ev["b_fix_2_8"].astype(int)
    rng = np.random.default_rng(seed); ev = ev.assign(_o=rng.random(len(ev)))
    by = {k: v for k, v in ev.groupby("di")}
    eq = start; op = []; held = set(); curve = []; taken = []
    for i, day in enumerate(cal):
        for p in [p for p in op if p[0] <= i]:
            eq += p[1]; op.remove(p); held.discard(p[2])
        t_ = by.get(i)
        if t_ is not None:
            gross = sum(p[3] for p in op)
            for _, r in t_.sort_values("_o").iterrows():
                if len(op) >= slots or r.symbol in held: continue
                sd = 2.0*r.atr_at_entry/r.entry
                if not np.isfinite(sd) or sd <= 0: continue
                n_ = min(eq*risk/sd, eq/slots)
                if gross + n_ > eq: continue
                gross += n_
                op.append((int(r.xd), n_*r["x_fix_2_8"]/100.0, r.symbol, n_))
                held.add(r.symbol); taken.append(r["x_fix_2_8"])
        curve.append((day, eq + sum(p[1] for p in op)))
    cv = pd.Series(dict(curve)).sort_index()
    yrs = (cv.index[-1]-cv.index[0]).days/365.25
    rr = cv.pct_change().dropna()
    return dict(total=100*(cv.iloc[-1]/start-1), cagr=100*((cv.iloc[-1]/start)**(1/yrs)-1),
                dd=100*(cv/cv.cummax()-1).min(),
                sharpe=rr.mean()/rr.std()*np.sqrt(252) if rr.std()>0 else np.nan,
                taken=len(taken), avgt=float(np.mean(taken)) if taken else np.nan)

A0, A1 = "2024-09-04", "2026-09-04"
for nm, lo, hi in (("LAST 2 YEARS", A0, A1), ("FULL WINDOW", "2021-04-12", "2026-09-04")):
    cal = np.sort(wide.index[(wide.index >= lo) & (wide.index <= hi)].unique().values)
    s = d[(d.date >= lo) & (d.date <= hi)]
    s7 = s[s.score.eq(7.0)]
    SETS = {
        "7/7 only": s7,
        "7/7 + >=10 Cr": s7[s7.turnover_cr.ge(10)],
        "7/7 + high-vol gate": s7[s7.hv.eq(1)],
        "7/7 + >=10 Cr + high-vol": s7[s7.turnover_cr.ge(10) & s7.hv.eq(1)],
        "7/7 + >=10Cr + hv + EMA200": s7[s7.turnover_cr.ge(10) & s7.hv.eq(1) & s7.dist_ema200_atr.le(0.96)],
    }
    print("\n" + "=" * 118)
    print(f"{nm} — 7/7 combinations, 15 slots, unlevered, median of 6 selection orders")
    print("=" * 118)
    rows = []
    for k, ev in SETS.items():
        yv = ev["x_fix_2_8"]; w = yv[yv > 0]; l = yv[yv <= 0]
        r = [run(ev, cal, 15, seed=q) for q in range(6)]
        rows.append({"set": k, "signals": len(ev),
                     "win%": round(100*(yv > 0).mean(), 1), "avg%": round(yv.mean(), 2),
                     "PF": round(w.sum()/-l.sum(), 2),
                     "taken": int(np.median([q["taken"] for q in r])),
                     "avg% taken": round(np.median([q["avgt"] for q in r]), 2),
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

    if nm == "LAST 2 YEARS":
        print("\n  slot sensitivity for 7/7 + >=10 Cr:")
        ev = SETS["7/7 + >=10 Cr"]
        for slots in (5, 10, 15, 20, 30):
            r = [run(ev, cal, slots, seed=q) for q in range(6)]
            print(f"    {slots:>3} slots -> total {np.median([q['total'] for q in r]):+6.1f}%  "
                  f"taken {int(np.median([q['taken'] for q in r])):>4}  "
                  f"maxDD {np.median([q['dd'] for q in r]):+.1f}%  "
                  f"Sharpe {np.median([q['sharpe'] for q in r]):.2f}")
