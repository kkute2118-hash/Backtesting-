"""Only the video's 7-out-of-7 zones. Does the quality cost pay for itself
once capacity is the binding constraint?"""
import numpy as np, pandas as pd, sqlite3
pd.set_option("display.width", 210)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"
EXIT, BAR = "x_fix_2_8", "b_fix_2_8"

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
xx = pd.read_parquet("/tmp/gtf/exits.parquet")
d = pd.concat([d, xx[[c for c in xx.columns if c[:2] in ("x_", "b_")]]], axis=1)
d = d[(d.gap_through == 0) & d[EXIT].notna()].copy()
c = pd.read_parquet("/tmp/gtf/control.parquet"); c["date"] = pd.to_datetime(c["date"])
cx = pd.read_parquet("/tmp/gtf/control_exits.parquet")
c = pd.concat([c.reset_index(drop=True), cx[[k for k in cx.columns if k.startswith("x_")]].reset_index(drop=True)], axis=1)

con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt,symbol,close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()

def stats(s, label):
    s = np.asarray(s, float); s = s[np.isfinite(s)]
    if len(s) < 20: return {"set": label, "n": len(s)}
    w = s[s > 0]; l = s[s <= 0]
    return {"set": label, "n": len(s), "win%": round(100*len(w)/len(s), 1),
            "avg%": round(s.mean(), 2), "PF": round(w.sum()/-l.sum(), 2) if l.sum() < 0 else np.inf}

A0, A1 = "2024-09-04", "2026-09-04"
win2 = (d.date >= A0) & (d.date <= A1)
print("=" * 96)
print("SCORE 7/7 vs everything else, exit = stop 2 ATR / target 8 ATR / 60 bars")
print("=" * 96)
for nm, m in (("FULL WINDOW 2021-2026", pd.Series(True, index=d.index)),
              ("LAST 2 YEARS", win2)):
    print(f"\n{nm}")
    rows = [stats(d[m & d.score.eq(7.0)][EXIT], "score 7/7 only"),
            stats(d[m & d.score.ge(6.0)][EXIT], "score >= 6"),
            stats(d[m & d.score.lt(7.0)][EXIT], "score < 7"),
            stats(d[m][EXIT], "every arrival")]
    print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 96)
print("Score 7/7 by year")
print("=" * 96)
S7 = d[d.score.eq(7.0)]
g = S7.set_index("date").groupby(pd.Grouper(freq="YE"))[EXIT]
print(pd.DataFrame({"n": g.size(), "win%": g.apply(lambda z: 100*(z>0).mean()),
                    "avg%": g.mean()}).round(1).to_string())

print("\nplacebo over the same span, same exit:")
print(" ", stats(c[EXIT], "matched placebo"))

# ---------------------------------------------------------------- portfolio
def run(ev, cal, slots=30, risk=0.015, seed=0, start=1e6):
    ev = ev.dropna(subset=[EXIT, BAR]).sort_values("date").copy()
    dmap = {v: i for i, v in enumerate(cal)}
    ev["di"] = ev.date.map(dmap); ev = ev[ev.di.notna()]; ev["di"] = ev.di.astype(int)
    ev["xd"] = ev.di + ev[BAR].astype(int)
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
                sd = 2.0 * r.atr_at_entry / r.entry
                if not np.isfinite(sd) or sd <= 0: continue
                n_ = min(eq * risk / sd, eq / slots)
                if gross + n_ > eq: continue
                gross += n_
                op.append((int(r.xd), n_ * r[EXIT] / 100.0, r.symbol, n_))
                held.add(r.symbol); taken.append(r[EXIT])
        curve.append((day, eq + sum(p[1] for p in op)))
    cv = pd.Series(dict(curve)).sort_index()
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    rr = cv.pct_change().dropna()
    return dict(total=100*(cv.iloc[-1]/start-1),
                cagr=100*((cv.iloc[-1]/start)**(1/yrs)-1),
                dd=100*(cv/cv.cummax()-1).min(),
                sharpe=rr.mean()/rr.std()*np.sqrt(252) if rr.std()>0 else np.nan,
                taken=len(taken), avg_taken=float(np.mean(taken)) if taken else np.nan), cv

for nm, lo, hi in (("LAST 2 YEARS", A0, A1), ("FULL WINDOW", "2021-04-12", "2026-09-04")):
    cal = np.sort(wide.index[(wide.index >= lo) & (wide.index <= hi)].unique().values)
    sub = d[(d.date >= lo) & (d.date <= hi)]
    print("\n" + "=" * 96)
    print(f"PORTFOLIO — {nm} (unlevered, 1.5% risk, one per symbol)")
    print("=" * 96)
    rows = []
    for setname, ev in (("score 7/7 only", sub[sub.score.eq(7.0)]),
                        ("score 7/7, >=10 Cr", sub[sub.score.eq(7.0) & sub.turnover_cr.ge(10)]),
                        ("every arrival", sub)):
        for slots in (10, 20, 30):
            r = [run(ev, cal, slots, seed=q)[0] for q in range(6)]
            rows.append({"set": setname, "slots": slots,
                         "signals": len(ev),
                         "taken": int(np.median([q["taken"] for q in r])),
                         "avg% taken": round(np.median([q["avg_taken"] for q in r]), 2),
                         "total%": round(np.median([q["total"] for q in r]), 1),
                         "CAGR%": round(np.median([q["cagr"] for q in r]), 1),
                         "maxDD%": round(np.median([q["dd"] for q in r]), 1),
                         "Sharpe": round(np.median([q["sharpe"] for q in r]), 2)})
    print(pd.DataFrame(rows).to_string(index=False))
    sl = idx.loc[cal[0]:cal[-1]]
    yrs = (sl.index[-1]-sl.index[0]).days/365.25
    rr = sl.pct_change().dropna()
    print(f"  benchmark buy & hold: total {100*(sl.iloc[-1]/sl.iloc[0]-1):+.1f}%  "
          f"CAGR {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):+.1f}%  "
          f"maxDD {100*(sl/sl.cummax()-1).min():.1f}%  Sharpe {rr.mean()/rr.std()*np.sqrt(252):.2f}")
