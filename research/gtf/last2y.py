"""GTF-D14 over the last two years. Walk-forward, as deployed."""
import numpy as np, pandas as pd, sqlite3
from sklearn.ensemble import HistGradientBoostingRegressor
pd.set_option("display.width", 200)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"
A0, A1 = "2024-09-04", "2026-09-04"
MAX_APPROACH, MIN_TURN = 9.66, 10.0

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
xx = pd.read_parquet("/tmp/gtf/exits.parquet")
d = pd.concat([d, xx[[c for c in xx.columns if c[:2] in ("x_", "b_")]]], axis=1)
d = d[(d.gap_through == 0) & d["x_fix_2_8"].notna()].copy().sort_values("date").reset_index(drop=True)
d["y"] = d["x_fix_2_8"]; d["q"] = d.date.dt.to_period("Q")

FEATS = ["risk_pct", "zone_h_pct", "n_base", "legout_n", "gap", "closing_ok",
         "legout_atr", "zone_age", "arrival", "score", "atr_pct", "relvol", "rsi14",
         "dist_ema200_atr", "dist_ema50_atr", "dist_ema20_atr", "prev_close_pct",
         "gap_in", "target_r_available", "w_trend50", "w_trend10", "m_trend50",
         "d_trend", "m_curve", "w_curve", "coincide", "risk_atr"]
d["pred"] = np.nan; d["thr"] = np.nan
for f, p in (("risk_pct", 40), ("legout_atr", 50), ("atr_pct", 50), ("prev_close_pct", 50)):
    d[f"th_{f}"] = np.nan
for qq in sorted(d.q.unique()):
    past = d[(d.q < qq) & (d.date < qq.start_time - pd.Timedelta(days=95))]
    if len(past) < 6000: continue
    use = [f for f in FEATS if past[f].notna().sum() > 50 and past[f].nunique() > 1]
    m = HistGradientBoostingRegressor(max_depth=3, max_iter=250, learning_rate=0.05,
                                      min_samples_leaf=80, l2_regularization=1.0,
                                      random_state=0).fit(past[use].to_numpy(), past.y.to_numpy())
    sel = d.q == qq
    d.loc[sel, "pred"] = m.predict(d.loc[sel, use].to_numpy())
    d.loc[sel, "thr"] = float(np.percentile(m.predict(past[use].to_numpy()), 90))
    for f, p in (("risk_pct", 40), ("legout_atr", 50), ("atr_pct", 50), ("prev_close_pct", 50)):
        d.loc[sel, f"th_{f}"] = float(np.nanpercentile(past[f], p))

W = d[d.pred.notna() & (d.date >= A0) & (d.date <= A1)].copy()
rules = ((W.risk_pct >= W.th_risk_pct) & (W.legout_atr >= W.th_legout_atr)
         & (W.atr_pct >= W.th_atr_pct) & (W.prev_close_pct >= W.th_prev_close_pct)
         & (W.dist_ema200_atr <= 0.96))
guards = (W.prev_close_pct <= MAX_APPROACH) & (W.turnover_cr >= MIN_TURN)
S = W[(rules | (W.pred >= W.thr)) & guards]

s = S.y.to_numpy(); w = s[s > 0]; l = s[s <= 0]
print("=" * 74)
print(f"GTF-D14, LAST TWO YEARS  ({A0} to {A1}), walk-forward")
print("=" * 74)
print(f"  trades                {len(s):>10,}")
print(f"  distinct symbols      {S.symbol.nunique():>10,}")
print(f"  WIN RATE              {100*len(w)/len(s):>9.1f} %")
print(f"  average per trade     {s.mean():>+9.2f} %")
print(f"  average winner        {w.mean():>+9.2f} %")
print(f"  average loser         {l.mean():>+9.2f} %")
print(f"  profit factor         {w.sum()/-l.sum():>9.2f}")

# portfolio ROI
con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt,symbol,close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
CAL = np.sort(wide.index[(wide.index >= A0) & (wide.index <= A1)].unique().values)
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()

def run(ev, slots=30, risk=0.015, seed=0, start=1e6):
    ev = ev.dropna(subset=["x_fix_2_8", "b_fix_2_8"]).sort_values("date").copy()
    dmap = {v: i for i, v in enumerate(CAL)}
    ev["di"] = ev.date.map(dmap); ev = ev[ev.di.notna()]; ev["di"] = ev.di.astype(int)
    ev["xd"] = ev.di + ev["b_fix_2_8"].astype(int)
    rng = np.random.default_rng(seed); ev = ev.assign(_o=rng.random(len(ev)))
    by = {k: v for k, v in ev.groupby("di")}
    eq = start; op = []; held = set(); curve = []; taken = []
    for i, day in enumerate(CAL):
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
                op.append((int(r.xd), n_ * r["x_fix_2_8"] / 100.0, r.symbol, n_)); held.add(r.symbol)
                taken.append(r["x_fix_2_8"])
        curve.append((day, eq + sum(p[1] for p in op)))
    cv = pd.Series(dict(curve)).sort_index()
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    rr = cv.pct_change().dropna()
    return (100 * (cv.iloc[-1] / start - 1), 100 * ((cv.iloc[-1] / start) ** (1 / yrs) - 1),
            100 * (cv / cv.cummax() - 1).min(), rr.mean() / rr.std() * np.sqrt(252), cv,
            len(taken), float(np.mean(taken)) if taken else np.nan)

res = [run(S, seed=q) for q in range(8)]
print(f"\n  trades actually TAKEN by the portfolio: {int(np.median([r[5] for r in res]))} "
      f"of {len(S)} signals   avg of taken {np.median([r[6] for r in res]):+.2f}%")
tot = [r[0] for r in res]; cag = [r[1] for r in res]; dd = [r[2] for r in res]; sh = [r[3] for r in res]
print(f"\n  PORTFOLIO ROI (unlevered, 1.5% risk/trade, 30 slots, no leverage)")
print(f"  total return over 2 yrs {np.median(tot):>+8.1f} %      (range {min(tot):+.1f} to {max(tot):+.1f})")
print(f"  CAGR                    {np.median(cag):>+8.1f} %")
print(f"  max drawdown            {np.median(dd):>+8.1f} %")
print(f"  Sharpe                  {np.median(sh):>8.2f}")

sl = idx.loc[CAL[0]:CAL[-1]]
yrs = (sl.index[-1] - sl.index[0]).days / 365.25
rr = sl.pct_change().dropna()
print(f"\n  BENCHMARK equal-weight universe, buy and hold, same 2 years")
print(f"  total return            {100*(sl.iloc[-1]/sl.iloc[0]-1):>+8.1f} %")
print(f"  CAGR                    {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):>+8.1f} %")
print(f"  max drawdown            {100*(sl/sl.cummax()-1).min():>+8.1f} %")
print(f"  Sharpe                  {rr.mean()/rr.std()*np.sqrt(252):>8.2f}")

print("\n  slot sensitivity (total 2-yr return):")
for sl_ in (10, 20, 30, 50, 80):
    rs = [run(S, slots=sl_, seed=q) for q in range(5)]
    print(f"    {sl_:>3} slots -> {np.median([r[0] for r in rs]):+7.1f} %   "
          f"taken {int(np.median([r[5] for r in rs])):>4}   "
          f"maxDD {np.median([r[2] for r in rs]):+.1f}%")

print("\n  by half-year (trade average, not portfolio):")
g = S.set_index("date").groupby(pd.Grouper(freq="2QE"))["y"]
print(pd.DataFrame({"trades": g.size(), "win%": g.apply(lambda z: 100*(z>0).mean()),
                    "avg%": g.mean()}).round(1).to_string())
