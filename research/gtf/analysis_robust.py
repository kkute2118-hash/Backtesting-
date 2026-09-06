"""Try to break the walk-forward system."""
import numpy as np, pandas as pd, sqlite3
from sklearn.ensemble import HistGradientBoostingRegressor
pd.set_option("display.width", 250)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"

W = pd.read_parquet("/tmp/gtf/walkforward.parquet"); W["date"] = pd.to_datetime(W["date"])
con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt,symbol,close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
CAL = np.sort(wide.index.unique().values)
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()

def run(ev, exitc, barc, max_pos=20, risk_frac=0.015, seed=0, start=1e6):
    ev = ev.dropna(subset=[exitc, barc]).sort_values("date").copy()
    dmap = {v: i for i, v in enumerate(CAL)}
    ev["di"] = ev.date.map(dmap); ev = ev[ev.di.notna()]; ev["di"] = ev.di.astype(int)
    ev["xd"] = ev.di + ev[barc].astype(int)
    rng = np.random.default_rng(seed); ev = ev.assign(_o=rng.random(len(ev)))
    by = {k: v for k, v in ev.groupby("di")}
    eq = start; op = []; held = set(); curve = []; invested_days = 0
    for i, day in enumerate(CAL):
        for p in [p for p in op if p[0] <= i]:
            eq += p[1]; op.remove(p); held.discard(p[2])
        t_ = by.get(i)
        if t_ is not None:
            gross = sum(p[3] for p in op)
            for _, r in t_.sort_values("_o").iterrows():
                if len(op) >= max_pos or r.symbol in held: continue
                sd = 2.0 * r.atr_at_entry / r.entry
                if not np.isfinite(sd) or sd <= 0: continue
                notional = min(eq * risk_frac / sd, eq / max_pos)
                if gross + notional > eq: continue
                gross += notional
                op.append((int(r.xd), notional * r[exitc] / 100.0, r.symbol, notional))
                held.add(r.symbol)
        if op: invested_days += 1
        curve.append((day, eq + sum(p[1] for p in op)))
    cv = pd.Series(dict(curve)).sort_index().loc[ev.date.min():]
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    rr = cv.pct_change().dropna()
    return dict(CAGR=100 * ((cv.iloc[-1] / cv.iloc[0]) ** (1 / yrs) - 1),
                maxDD=100 * (cv / cv.cummax() - 1).min(),
                Sharpe=rr.mean() / rr.std() * np.sqrt(252),
                invested=100 * invested_days / len(CAL)), cv

score = W.pred >= W.thr
S = W[score]

print("=" * 108)
print("1. Does it survive a different exit? (the exit was picked after seeing val/test)")
print("=" * 108)
for p in ("fix_2_4", "fix_2_6", "fix_2_8", "trail_2_4", "trail_2_3", "be2_trail4"):
    res = [run(S, f"x_{p}", f"b_{p}", seed=s)[0] for s in range(6)]
    print(f"  {p:<12} CAGR {np.median([r['CAGR'] for r in res]):6.2f}%  "
          f"maxDD {np.median([r['maxDD'] for r in res]):7.2f}%  "
          f"Sharpe {np.median([r['Sharpe'] for r in res]):.2f}  "
          f"invested {np.median([r['invested'] for r in res]):.0f}% of days")

print("\n" + "=" * 108)
print("2. Is it the illiquidity tilt? Refit the model with turnover REMOVED,")
print("   fully walk-forward again, and apply a hard liquidity floor.")
print("=" * 108)
d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
xx = pd.read_parquet("/tmp/gtf/exits.parquet")
d = pd.concat([d, xx[[c for c in xx.columns if c[:2] in ("x_", "b_")]]], axis=1)
d = d[(d.gap_through == 0) & d["x_fix_2_8"].notna()].copy().sort_values("date").reset_index(drop=True)
d["y"] = d["x_fix_2_8"]; d["q"] = d.date.dt.to_period("Q")
F0 = ["risk_pct", "zone_h_pct", "n_base", "legout_n", "gap", "closing_ok",
      "legout_atr", "zone_age", "arrival", "score", "atr_pct", "relvol", "rsi14",
      "dist_ema200_atr", "dist_ema50_atr", "dist_ema20_atr", "prev_close_pct",
      "gap_in", "target_r_available", "w_trend50", "w_trend10", "m_trend50",
      "d_trend", "m_curve", "w_curve", "coincide", "risk_atr"]     # no turnover
d["pred2"] = np.nan; d["thr2"] = np.nan
for qq in sorted(d.q.unique()):
    past = d[(d.q < qq) & (d.date < qq.start_time - pd.Timedelta(days=95))]
    if len(past) < 6000: continue
    use = [f for f in F0 if past[f].notna().sum() > 50 and past[f].nunique() > 1]
    m = HistGradientBoostingRegressor(max_depth=3, max_iter=250, learning_rate=0.05,
                                      min_samples_leaf=80, l2_regularization=1.0,
                                      random_state=0).fit(past[use].to_numpy(), past.y.to_numpy())
    sel = d.q == qq
    d.loc[sel, "pred2"] = m.predict(d.loc[sel, use].to_numpy())
    d.loc[sel, "thr2"] = float(np.percentile(m.predict(past[use].to_numpy()), 90))
D = d[d.pred2.notna()]
for nm, sub in (("no-turnover model", D[D.pred2 >= D.thr2]),
                ("  + floor 10 Cr/day", D[(D.pred2 >= D.thr2) & D.turnover_cr.ge(10)]),
                ("  + floor 25 Cr/day", D[(D.pred2 >= D.thr2) & D.turnover_cr.ge(25)])):
    s = sub["x_fix_2_8"]
    res = [run(sub, "x_fix_2_8", "b_fix_2_8", seed=q)[0] for q in range(6)]
    print(f"  {nm:<20} n={len(sub):>5} avg%={s.mean():+6.2f}  "
          f"CAGR {np.median([r['CAGR'] for r in res]):6.2f}%  "
          f"maxDD {np.median([r['maxDD'] for r in res]):7.2f}%  "
          f"Sharpe {np.median([r['Sharpe'] for r in res]):.2f}")

print("\n" + "=" * 108)
print("3. Model-choice sensitivity: different seeds and depths, same walk-forward")
print("=" * 108)
for depth, seed in ((2, 0), (3, 1), (3, 2), (4, 0), (5, 0)):
    d["p3"] = np.nan; d["t3"] = np.nan
    for qq in sorted(d.q.unique()):
        past = d[(d.q < qq) & (d.date < qq.start_time - pd.Timedelta(days=95))]
        if len(past) < 6000: continue
        use = [f for f in F0 if past[f].notna().sum() > 50 and past[f].nunique() > 1]
        m = HistGradientBoostingRegressor(max_depth=depth, max_iter=250, learning_rate=0.05,
                                          min_samples_leaf=80, l2_regularization=1.0,
                                          random_state=seed).fit(past[use].to_numpy(), past.y.to_numpy())
        sel = d.q == qq
        d.loc[sel, "p3"] = m.predict(d.loc[sel, use].to_numpy())
        d.loc[sel, "t3"] = float(np.percentile(m.predict(past[use].to_numpy()), 90))
    E = d[d.p3.notna()]; sub = E[E.p3 >= E.t3]
    res = [run(sub, "x_fix_2_8", "b_fix_2_8", seed=q)[0] for q in range(4)]
    print(f"  depth={depth} seed={seed}: n={len(sub):>5} avg%={sub['x_fix_2_8'].mean():+6.2f}  "
          f"CAGR {np.median([r['CAGR'] for r in res]):6.2f}%  "
          f"Sharpe {np.median([r['Sharpe'] for r in res]):.2f}")

print("\n" + "=" * 108)
print("4. Yearly, and the worst stretch")
print("=" * 108)
_, cv = run(S, "x_fix_2_8", "b_fix_2_8", seed=0)
yr = cv.resample("YE").last().pct_change().dropna() * 100
print("calendar-year returns %:"); print(yr.round(1).to_string())
dd = (cv / cv.cummax() - 1) * 100
print(f"\nworst drawdown {dd.min():.1f}% on {dd.idxmin().date()}")
und = (dd < -1).astype(int)
print(f"longest stretch under water: {(und.groupby((und != und.shift()).cumsum()).cumsum()).max()} trading days")
