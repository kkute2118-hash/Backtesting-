"""Phase 29/34: a no-trade filter, risk-adjusted numbers, and a portfolio run
with real capital constraints - because a per-trade average with unlimited
concurrency is not a thing anyone can actually trade."""
import numpy as np, pandas as pd, sqlite3
import candidates as K
pd.set_option("display.width", 250)

DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"
d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
d = d[d.gap_through == 0].copy()
d["p"] = K.pct_pnl(d); d["r"] = K.r_pnl(d)
TR = d[d.date < "2024-04-01"]
q = lambda f, pp: float(np.nanpercentile(TR[f], pp))
TH = dict(atr=q("atr_pct", 50), legout=q("legout_atr", 50),
          risk=q("risk_pct", 40), speed=q("prev_close_pct", 50))

def C12(x):
    return (x.risk_pct.ge(TH["risk"]) & x.legout_atr.ge(TH["legout"])
            & x.atr_pct.ge(TH["atr"]) & x.prev_close_pct.ge(TH["speed"])
            & x.dist_ema200_atr.le(0.96))

print("risk-normalised view of the volatility sweep (avg R, so bigger moves are")
print("not simply rewarded for being bigger):")
rows = []
for f in [2.0, 2.6, 3.24, 3.8, 4.5, 5.5]:
    s = d[(d.risk_pct.ge(TH["risk"]) & d.legout_atr.ge(TH["legout"])
           & d.atr_pct.ge(f) & d.prev_close_pct.ge(TH["speed"])
           & d.dist_ema200_atr.le(0.96))]
    rows.append({"atr_pct floor": f, "n": len(s), "avg%": s.p.mean(),
                 "avgR": s.r.mean(), "PF": s.p[s.p > 0].sum() / -s.p[s.p <= 0].sum()})
print(pd.DataFrame(rows).round(3).to_string(index=False))

# ---- market regime series
con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt, symbol, close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()
mk = pd.DataFrame({"mkt": idx})
# realised volatility of the equal-weight index, known on the day it is read
mk["vol20"] = mk.mkt.pct_change().rolling(20).std() * np.sqrt(252) * 100
mk["vol_med"] = mk.vol20.rolling(500, min_periods=120).median()   # expanding-ish, no peeking
mk["high_vol"] = (mk.vol20 > mk.vol_med).astype(int)
d = d.merge(mk[["vol20", "vol_med", "high_vol"]], left_on="date", right_index=True, how="left")

W = d[C12(d)].copy()
print("\n" + "=" * 110)
print("PHASE 29 - no-trade filter: market volatility regime (point-in-time median)")
print("=" * 110)
for nm, sub in (("C12, high-vol market", W[W.high_vol == 1]),
                ("C12, low-vol market", W[W.high_vol == 0])):
    print(" ", K.summarise(sub.p, nm, sub.r))
WF = W[W.high_vol == 1]
for split, m in (("train", WF.date < "2024-04-01"),
                 ("val", (WF.date >= "2024-04-01") & (WF.date < "2025-07-01")),
                 ("test", WF.date >= "2025-07-01")):
    print("  C13 =", split, K.summarise(WF[m].p, split, WF[m].r))

# ---------------------------------------------------------------- portfolio
print("\n" + "=" * 110)
print("PORTFOLIO SIMULATION - 1% of equity risked per trade, max concurrent positions")
print("capped, one position per symbol, trades taken in score order when the day is busy")
print("=" * 110)

def portfolio(ev, cal, max_pos=10, risk_frac=0.01, start=1_000_000.0):
    """cal is the trading-day calendar; exits are measured in trading days,
    not in the sparse set of days that happen to carry a signal."""
    ev = ev.sort_values("date").copy()
    ev["exit_bar"] = np.where(
        np.isfinite(ev.p),
        np.minimum(np.where(ev[K.STOP] >= 0, ev[K.STOP], 999),
                   np.where(ev[K.TGT] >= 0, ev[K.TGT], 999)), 999)
    ev["exit_bar"] = np.minimum(ev.exit_bar, K.HOLD)
    dmap = {v: i for i, v in enumerate(cal)}
    ev["di"] = ev.date.map(dmap)
    ev = ev[ev.di.notna()]
    ev["di"] = ev.di.astype(int)
    ev["exit_di"] = ev.di + ev.exit_bar.astype(int)
    days = cal
    eq = start
    open_pos = []          # (exit_di, pnl_amount)
    curve = []
    held = set()
    taken = 0
    by_day = {k: v for k, v in ev.groupby("di")}
    for i, day in enumerate(days):
        for pos in [p for p in open_pos if p[0] <= i]:
            eq += pos[1]; open_pos.remove(pos); held.discard(pos[2])
        todays = by_day.get(i)
        if todays is None:
            curve.append((day, eq + sum(p[1] for p in open_pos)))
            continue
        # tie-break by symbol name, which cannot know the outcome
        for _, t in todays.sort_values("symbol").iterrows():
            if len(open_pos) >= max_pos or t.symbol in held:
                continue
            if not np.isfinite(t.p):
                continue
            risk_amt = eq * risk_frac
            stop_dist = (t.entry - t[K.STOP.replace("_bar", "_px")]) / t.entry
            if not np.isfinite(stop_dist) or stop_dist <= 0:
                continue
            notional = min(risk_amt / stop_dist, eq * 0.25)   # no single position over 25%
            open_pos.append((int(t.exit_di), notional * t.p / 100.0, t.symbol))
            held.add(t.symbol); taken += 1
        curve.append((day, eq + sum(p[1] for p in open_pos)))
    cv = pd.Series(dict(curve)).sort_index()
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    cagr = (cv.iloc[-1] / start) ** (1 / yrs) - 1
    dd = (cv / cv.cummax() - 1).min()
    rets = cv.pct_change().dropna()
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else np.nan
    return {"max_pos": max_pos, "trades_taken": taken, "signals": len(ev),
            "final": cv.iloc[-1], "CAGR%": 100 * cagr,
            "maxDD%": 100 * dd, "Sharpe": sharpe, "years": round(yrs, 2)}, cv

CAL = np.sort(wide.index.unique().values)
rows = []
for mp in (5, 10, 15, 20, 30):
    st, cv = portfolio(WF, CAL, max_pos=mp)
    rows.append(st)
print(pd.DataFrame(rows).round(2).to_string(index=False))

st, cv = portfolio(WF, CAL, max_pos=10)
print("\nequity curve, year ends (max 10 positions, 1% risk):")
print(cv.resample("YE").last().round(0).to_string())

print("\nbuy-and-hold of the equal-weight universe over the same span:")
sl = idx.loc[cv.index[0]:cv.index[-1]]
yrs = (sl.index[-1] - sl.index[0]).days / 365.25
print(f"  CAGR {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):.2f}%   "
      f"maxDD {100*(sl/sl.cummax()-1).min():.2f}%")
