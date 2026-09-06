"""The portfolio the walk-forward signals actually produce.

Per-trade averages with unlimited concurrency are not a system. This runs the
walk-forward signals through real constraints - fixed fractional risk, a cap on
open positions, one position per symbol, no leverage - and puts the result next
to buying the universe.
"""
import numpy as np, pandas as pd, sqlite3
pd.set_option("display.width", 250)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"
EXIT, BARS = "x_fix_2_8", "b_fix_2_8"

W = pd.read_parquet("/tmp/gtf/walkforward.parquet")
W["date"] = pd.to_datetime(W["date"])
con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt,symbol,close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
CAL = np.sort(wide.index.unique().values)
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()

rules = (W.risk_pct >= W.th_risk_pct) & (W.legout_atr >= W.th_legout_atr) \
        & (W.atr_pct >= W.th_atr_pct) & (W.prev_close_pct >= W.th_prev_close_pct) \
        & (W.dist_ema200_atr <= 0.96)
score = W.pred >= W.thr
SETS = {"rules only": W[rules],
        "score only": W[score],
        "rules AND score": W[rules & score],
        "score, >=10 Cr/day": W[score & W.turnover_cr.ge(10)],
        "rules AND score, >=10 Cr": W[rules & score & W.turnover_cr.ge(10)]}

def run(ev, max_pos, risk_frac, seed, start=1e6, cash_drag=True):
    ev = ev.dropna(subset=[EXIT, BARS]).sort_values("date").copy()
    dmap = {v: i for i, v in enumerate(CAL)}
    ev["di"] = ev.date.map(dmap); ev = ev[ev.di.notna()]; ev["di"] = ev.di.astype(int)
    ev["xd"] = ev.di + ev[BARS].astype(int)
    rng = np.random.default_rng(seed)
    ev = ev.assign(_o=rng.random(len(ev)))
    by = {k: v for k, v in ev.groupby("di")}
    eq = start; opened = []; held = set(); curve = []; taken = 0
    for i, day in enumerate(CAL):
        for p in [p for p in opened if p[0] <= i]:
            eq += p[1]; opened.remove(p); held.discard(p[2])
        t_ = by.get(i)
        if t_ is not None:
            gross = sum(p[3] for p in opened)
            for _, r in t_.sort_values("_o").iterrows():
                if len(opened) >= max_pos or r.symbol in held:
                    continue
                sd = 2.0 * r.atr_at_entry / r.entry           # stop is 2 ATR
                if not np.isfinite(sd) or sd <= 0:
                    continue
                notional = min(eq * risk_frac / sd, eq / max_pos)
                if cash_drag and gross + notional > eq:
                    continue
                gross += notional
                opened.append((int(r.xd), notional * r[EXIT] / 100.0, r.symbol, notional))
                held.add(r.symbol); taken += 1
        curve.append((day, eq + sum(p[1] for p in opened)))
    cv = pd.Series(dict(curve)).sort_index()
    cv = cv.loc[ev.date.min():]
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    rr = cv.pct_change().dropna()
    return dict(taken=taken, signals=len(ev),
                CAGR=100 * ((cv.iloc[-1] / cv.iloc[0]) ** (1 / yrs) - 1),
                maxDD=100 * (cv / cv.cummax() - 1).min(),
                Sharpe=rr.mean() / rr.std() * np.sqrt(252) if rr.std() > 0 else np.nan), cv

print("=" * 122)
print("PORTFOLIO on fully walk-forward signals - unlevered, 1.5% risked per trade,")
print("one position per symbol, median of 8 random selection orders")
print("=" * 122)
rows = []
for nm, ev in SETS.items():
    for mp in (10, 20, 30):
        res = [run(ev, mp, 0.015, s)[0] for s in range(8)]
        rows.append({"signal set": nm, "slots": mp,
                     "taken": int(np.median([r["taken"] for r in res])),
                     "signals": res[0]["signals"],
                     "CAGR%": np.median([r["CAGR"] for r in res]),
                     "maxDD%": np.median([r["maxDD"] for r in res]),
                     "Sharpe": np.median([r["Sharpe"] for r in res])})
t = pd.DataFrame(rows)
print(t.round(2).to_string(index=False))

sl = idx.loc[pd.Timestamp(W.date.min()):]
yrs = (sl.index[-1] - sl.index[0]).days / 365.25
rr = sl.pct_change().dropna()
print(f"\nBENCHMARK  equal-weight universe, buy and hold, same span "
      f"({sl.index[0].date()} .. {sl.index[-1].date()}):")
print(f"  CAGR {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):.2f}%   "
      f"maxDD {100*(sl/sl.cummax()-1).min():.2f}%   "
      f"Sharpe {rr.mean()/rr.std()*np.sqrt(252):.2f}")

print("\n" + "=" * 122)
print("Risk per trade sweep, best signal set, 20 slots")
print("=" * 122)
best = SETS["score only"]
for rf in (0.01, 0.015, 0.02, 0.03):
    res = [run(best, 20, rf, s)[0] for s in range(8)]
    print(f"  {rf*100:.1f}% risk/trade -> CAGR {np.median([r['CAGR'] for r in res]):6.2f}%  "
          f"maxDD {np.median([r['maxDD'] for r in res]):7.2f}%  "
          f"Sharpe {np.median([r['Sharpe'] for r in res]):.2f}")

_, cv = run(best, 20, 0.015, 0)
print("\nequity curve, year ends (score only, 20 slots, 1.5% risk):")
print(cv.resample("YE").last().round(0).to_string())
print("\ntime invested (share of days with at least one open position):")
_, cv2 = run(best, 20, 0.015, 0)
print(f"  correlation of daily returns with the index: "
      f"{pd.DataFrame({'s':cv.pct_change(),'m':idx.pct_change()}).dropna().corr().iloc[0,1]:.3f}")
