"""Final adversarial checks before writing anything down."""
import numpy as np, pandas as pd, sqlite3
import candidates as K
pd.set_option("display.width", 250)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
d = d[d.gap_through == 0].copy(); d["p"] = K.pct_pnl(d); d["r"] = K.r_pnl(d)
TR = d[d.date < "2024-04-01"]
q = lambda f, pp: float(np.nanpercentile(TR[f], pp))
TH = dict(atr=q("atr_pct", 50), legout=q("legout_atr", 50),
          risk=q("risk_pct", 40), speed=q("prev_close_pct", 50))

con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt, symbol, close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()
mk = pd.DataFrame({"mkt": idx})
mk["vol20"] = mk.mkt.pct_change().rolling(20).std() * np.sqrt(252) * 100
mk["vol_med"] = mk.vol20.rolling(500, min_periods=120).median()
mk["high_vol"] = (mk.vol20 > mk.vol_med).astype(int)
d = d.merge(mk[["high_vol"]], left_on="date", right_index=True, how="left")
W = d[(d.risk_pct.ge(TH["risk"]) & d.legout_atr.ge(TH["legout"])
       & d.atr_pct.ge(TH["atr"]) & d.prev_close_pct.ge(TH["speed"])
       & d.dist_ema200_atr.le(0.96) & d.high_vol.eq(1))].copy()
print(f"C13 signals: {len(W)}  symbols {W.symbol.nunique()}\n")

# ---------------------------------------------------------------- survivorship probe
print("=" * 110)
print("SURVIVORSHIP PROBE - is the edge concentrated in the stocks that went up anyway?")
print("(the store holds today's Nifty 500 applied to the whole window, so names that")
print(" were demoted or delisted are simply absent; this bounds the channel it works through)")
print("=" * 110)
bh = (wide.iloc[-1] / wide.bfill().iloc[0] - 1) * 100
per = W.groupby("symbol")["p"].agg(["size", "mean", "sum"])
per["buyhold%"] = bh.reindex(per.index)
per = per.dropna()
per["bh_q"] = pd.qcut(per["buyhold%"], 5, labels=False)
print(per.groupby("bh_q").agg(symbols=("mean", "size"), median_buyhold=("buyhold%", "median"),
                              avg_trade_pct=("mean", "mean"),
                              trades=("size", "sum")).round(2).to_string())
print(f"\ncorr(symbol avg trade %, symbol buy-and-hold %) = "
      f"{per['mean'].corr(per['buyhold%']):.3f}")
print("worst-quintile-by-buy-and-hold names still average "
      f"{per[per.bh_q==0]['mean'].mean():+.2f}% per trade")

# ---------------------------------------------------------------- selection variance
print("\n" + "=" * 110)
print("SELECTION VARIANCE - capacity binds hard, so which signals get taken matters")
print("=" * 110)
CAL = np.sort(wide.index.unique().values)
def portfolio(ev, max_pos, seed, risk_frac=0.01, start=1e6, lever_cap=1.0):
    ev = ev.sort_values("date").copy()
    ev["exit_bar"] = np.minimum(
        np.minimum(np.where(ev[K.STOP] >= 0, ev[K.STOP], 999),
                   np.where(ev[K.TGT] >= 0, ev[K.TGT], 999)), K.HOLD)
    dmap = {v: i for i, v in enumerate(CAL)}
    ev["di"] = ev.date.map(dmap); ev = ev[ev.di.notna()]; ev["di"] = ev.di.astype(int)
    ev["exit_di"] = ev.di + ev.exit_bar.astype(int)
    rng = np.random.default_rng(seed)
    ev = ev.assign(_o=rng.random(len(ev)))
    eq = start; open_pos = []; held = set(); curve = []
    by_day = {k: v for k, v in ev.groupby("di")}
    for i, day in enumerate(CAL):
        for pos in [p for p in open_pos if p[0] <= i]:
            eq += pos[1]; open_pos.remove(pos); held.discard(pos[2])
        t_ = by_day.get(i)
        if t_ is not None:
            gross = sum(p[3] for p in open_pos)
            for _, t in t_.sort_values("_o").iterrows():
                if len(open_pos) >= max_pos or t.symbol in held or not np.isfinite(t.p):
                    continue
                sd = (t.entry - t[K.STOP.replace("_bar", "_px")]) / t.entry
                if not np.isfinite(sd) or sd <= 0:
                    continue
                notional = min(eq * risk_frac / sd, eq / max_pos)
                if gross + notional > eq * lever_cap:      # no leverage
                    continue
                gross += notional
                open_pos.append((int(t.exit_di), notional * t.p / 100.0, t.symbol, notional))
                held.add(t.symbol)
        curve.append((day, eq + sum(p[1] for p in open_pos)))
    cv = pd.Series(dict(curve)).sort_index()
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    r = cv.pct_change().dropna()
    return (100 * ((cv.iloc[-1] / start) ** (1 / yrs) - 1),
            100 * (cv / cv.cummax() - 1).min(),
            r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan, cv)

rows = []
for mp in (10, 15, 20):
    res = [portfolio(W, mp, s)[:3] for s in range(12)]
    a = np.array(res)
    rows.append({"max_pos": mp, "CAGR% med": np.median(a[:, 0]),
                 "CAGR% p10": np.percentile(a[:, 0], 10),
                 "CAGR% p90": np.percentile(a[:, 0], 90),
                 "maxDD% med": np.median(a[:, 1]), "Sharpe med": np.median(a[:, 2])})
print("unlevered (gross exposure capped at 100% of equity), 12 random selection orders:")
print(pd.DataFrame(rows).round(2).to_string(index=False))

sl = idx.loc[CAL[0]:CAL[-1]]
yrs = (sl.index[-1] - sl.index[0]).days / 365.25
r = sl.pct_change().dropna()
print(f"\nbenchmark, equal-weight universe buy-and-hold: "
      f"CAGR {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):.2f}%  "
      f"maxDD {100*(sl/sl.cummax()-1).min():.2f}%  "
      f"Sharpe {r.mean()/r.std()*np.sqrt(252):.2f}")

_, _, _, cv = portfolio(W, 15, 0)
print("\nrepresentative unlevered curve (15 slots, seed 0), year ends:")
print(cv.resample("YE").last().round(0).to_string())
print("\ncorrelation of strategy daily returns with the equal-weight index:")
both = pd.DataFrame({"s": cv.pct_change(), "m": idx.pct_change()}).dropna()
print(f"  {both.s.corr(both.m):.3f}")
