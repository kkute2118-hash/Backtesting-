"""The configuration scan.py actually ships, evaluated walk-forward.

Earlier portfolio numbers were run on signal sets that did not carry the
scanner's own guards - no approach cap, no liquidity floor, turnover still in
the feature set. This applies all of them, so the headline matches the thing
that would actually have run.
"""
import numpy as np, pandas as pd, sqlite3
from sklearn.ensemble import HistGradientBoostingRegressor
pd.set_option("display.width", 250)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"
MAX_APPROACH, MIN_TURN = 9.66, 10.0

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
xx = pd.read_parquet("/tmp/gtf/exits.parquet")
d = pd.concat([d, xx[[c for c in xx.columns if c[:2] in ("x_", "b_")]]], axis=1)
d = d[(d.gap_through == 0) & d["x_fix_2_8"].notna()].copy().sort_values("date").reset_index(drop=True)
d["y"] = d["x_fix_2_8"]; d["q"] = d.date.dt.to_period("Q")

con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt,symbol,close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
CAL = np.sort(wide.index.unique().values)
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()
mk = pd.DataFrame({"mkt": idx})
mk["v20"] = mk.mkt.pct_change().rolling(20).std() * np.sqrt(252) * 100
mk["hv"] = (mk.v20 > mk.v20.rolling(500, min_periods=120).median()).astype(int)
d = d.merge(mk[["hv"]], left_on="date", right_index=True, how="left")

FEATS = ["risk_pct", "zone_h_pct", "n_base", "legout_n", "gap", "closing_ok",
         "legout_atr", "zone_age", "arrival", "score", "atr_pct", "relvol",
         "rsi14", "dist_ema200_atr", "dist_ema50_atr", "dist_ema20_atr",
         "prev_close_pct", "gap_in", "target_r_available", "w_trend50",
         "w_trend10", "m_trend50", "d_trend", "m_curve", "w_curve", "coincide",
         "risk_atr"]                                    # no turnover
d["pred"] = np.nan; d["thr"] = np.nan
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
W = d[d.pred.notna()].copy()

PROD = W[(W.pred >= W.thr) & (W.prev_close_pct <= MAX_APPROACH)
         & (W.turnover_cr >= MIN_TURN)]
PROD_HV = PROD[PROD.hv == 1]

def run(ev, max_pos=20, risk_frac=0.015, seed=0, start=1e6, col="x_fix_2_8", bar="b_fix_2_8"):
    ev = ev.dropna(subset=[col, bar]).sort_values("date").copy()
    dmap = {v: i for i, v in enumerate(CAL)}
    ev["di"] = ev.date.map(dmap); ev = ev[ev.di.notna()]; ev["di"] = ev.di.astype(int)
    ev["xd"] = ev.di + ev[bar].astype(int)
    rng = np.random.default_rng(seed); ev = ev.assign(_o=rng.random(len(ev)))
    by = {k: v for k, v in ev.groupby("di")}
    eq = start; op = []; held = set(); curve = []
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
                n_ = min(eq * risk_frac / sd, eq / max_pos)
                if gross + n_ > eq: continue
                gross += n_
                op.append((int(r.xd), n_ * r[col] / 100.0, r.symbol, n_)); held.add(r.symbol)
        curve.append((day, eq + sum(p[1] for p in op)))
    cv = pd.Series(dict(curve)).sort_index().loc[ev.date.min():]
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    rr = cv.pct_change().dropna()
    return dict(CAGR=100 * ((cv.iloc[-1] / cv.iloc[0]) ** (1 / yrs) - 1),
                maxDD=100 * (cv / cv.cummax() - 1).min(),
                Sharpe=rr.mean() / rr.std() * np.sqrt(252)), cv

print("=" * 112)
print("AS-DEPLOYED, fully walk-forward: no turnover feature, approach cap 9.66%,")
print("liquidity floor 10 Cr/day, one position per symbol, unlevered")
print("=" * 112)
for nm, ev in (("production set", PROD), ("+ high-vol gate only", PROD_HV)):
    s = ev.y
    w = s[s > 0]; l = s[s <= 0]
    print(f"\n{nm}: {len(ev)} signals   win {100*(s>0).mean():.1f}%   "
          f"avg {s.mean():+.2f}%   PF {w.sum()/-l.sum():.2f}")
    rows = []
    for mp in (10, 20, 30):
        r = [run(ev, mp, seed=q)[0] for q in range(8)]
        rows.append({"slots": mp, "CAGR%": np.median([q["CAGR"] for q in r]),
                     "maxDD%": np.median([q["maxDD"] for q in r]),
                     "Sharpe": np.median([q["Sharpe"] for q in r]),
                     "CAGR p10": np.percentile([q["CAGR"] for q in r], 10),
                     "CAGR p90": np.percentile([q["CAGR"] for q in r], 90)})
    print(pd.DataFrame(rows).round(2).to_string(index=False))

sl = idx.loc[pd.Timestamp(W.date.min()):]
yrs = (sl.index[-1] - sl.index[0]).days / 365.25
rr = sl.pct_change().dropna()
print(f"\nBENCHMARK equal-weight buy-and-hold {sl.index[0].date()}..{sl.index[-1].date()}: "
      f"CAGR {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):.2f}%  "
      f"maxDD {100*(sl/sl.cummax()-1).min():.2f}%  Sharpe {rr.mean()/rr.std()*np.sqrt(252):.2f}")

_, cv = run(PROD, 20, seed=0)
print("\nproduction equity curve, year ends (20 slots):")
print(cv.resample("YE").last().round(0).to_string())
print("\ncalendar-year returns %:")
print((cv.resample("YE").last().pct_change().dropna() * 100).round(1).to_string())
both = pd.DataFrame({"s": cv.pct_change(), "m": idx.pct_change()}).dropna()
print(f"\ncorrelation with the index: {both.s.corr(both.m):.3f}")
PROD.to_parquet("/tmp/gtf/production_signals.parquet", index=False)

# ---------------------------------------------------------------- fair fight
print("\n" + "=" * 112)
print("DID THE MODEL ACTUALLY HELP? Same guards on both, walk-forward, unlevered")
print("=" * 112)
guards = (W.prev_close_pct <= MAX_APPROACH) & (W.turnover_cr >= MIN_TURN)
rules = ((W.risk_pct >= W.th_risk_pct) & (W.legout_atr >= W.th_legout_atr)
         & (W.atr_pct >= W.th_atr_pct) & (W.prev_close_pct >= W.th_prev_close_pct)
         & (W.dist_ema200_atr <= 0.96)) if "th_risk_pct" in W.columns else None
if rules is None:
    wf = pd.read_parquet("/tmp/gtf/walkforward.parquet")
    wf["date"] = pd.to_datetime(wf["date"])
    key = ["symbol", "date", "bar"]
    W2 = W.merge(wf[key + ["th_risk_pct", "th_legout_atr", "th_atr_pct",
                           "th_prev_close_pct"]], on=key, how="left")
    W = W2
    rules = ((W.risk_pct >= W.th_risk_pct) & (W.legout_atr >= W.th_legout_atr)
             & (W.atr_pct >= W.th_atr_pct) & (W.prev_close_pct >= W.th_prev_close_pct)
             & (W.dist_ema200_atr <= 0.96))
    guards = (W.prev_close_pct <= MAX_APPROACH) & (W.turnover_cr >= MIN_TURN)

SETS = {"five hand rules": W[rules & guards],
        "learned score": W[(W.pred >= W.thr) & guards],
        "both": W[rules & (W.pred >= W.thr) & guards],
        "either": W[(rules | (W.pred >= W.thr)) & guards]}
rows = []
for nm, ev in SETS.items():
    s = ev.y; w_ = s[s > 0]; l_ = s[s <= 0]
    r = [run(ev, 30, seed=q)[0] for q in range(8)]
    rows.append({"signal set": nm, "n": len(ev), "win%": 100 * (s > 0).mean(),
                 "avg%": s.mean(), "PF": w_.sum() / -l_.sum(),
                 "CAGR%": np.median([q["CAGR"] for q in r]),
                 "maxDD%": np.median([q["maxDD"] for q in r]),
                 "Sharpe": np.median([q["Sharpe"] for q in r])})
print(pd.DataFrame(rows).round(2).to_string(index=False))
