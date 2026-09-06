"""Run GTF-D13 on the prior audit's exact window and list the actual trades.

Audit window: 2024-09-04 .. 2026-09-04, Nifty 500 daily. Same window, same
universe, same cost model as research/strategy_config.proposed.json, so the
numbers sit next to that file's headline rather than floating free.
"""
import numpy as np, pandas as pd, sqlite3
import candidates as K
pd.set_option("display.width", 250)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
d = d[d.gap_through == 0].copy()
d["p"] = K.pct_pnl(d); d["r"] = K.r_pnl(d)

# thresholds are the ones already fixed on pre-2024-04 data. The audit window
# overlaps that by seven months, so this is NOT a clean out-of-sample read for
# the first seven months; the split further down separates them.
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

def C12(x):
    return (x.risk_pct.ge(TH["risk"]) & x.legout_atr.ge(TH["legout"])
            & x.atr_pct.ge(TH["atr"]) & x.prev_close_pct.ge(TH["speed"])
            & x.dist_ema200_atr.le(0.96))

A0, A1 = "2024-09-04", "2026-09-04"
win = (d.date >= A0) & (d.date <= A1)
print("=" * 112)
print(f"AUDIT WINDOW {A0} .. {A1}   (the window research/strategy_config.proposed.json used)")
print("=" * 112)
rows = []
for nm, m in (("every GTF arrival", win),
              ("C12 (five filters)", win & C12(d)),
              ("C13 (+ high-vol gate)", win & C12(d) & d.high_vol.eq(1))):
    s = d[m]
    rows.append({**K.summarise(s.p, nm, s.r), "symbols": s.symbol.nunique()})
t = pd.DataFrame(rows)
print(t[["strategy", "n", "symbols", "win%", "avg%", "avgR", "PF", "maxDD%", "tot%"]].round(3).to_string(index=False))

print("\nfor comparison, the prior audit's gated S1-S4 record on this same window:")
print("  2,357 trades   win 26.1%   expectancy -0.1885 R   PF 0.74   max DD -629.5 R")

W = d[win & C12(d) & d.high_vol.eq(1)].copy()
print(f"\nsplit inside the audit window (the first 7 months overlap the training data):")
for nm, m in (("2024-09..2025-06 (overlaps train tail / val)", W.date < "2025-07-01"),
              ("2025-07..2026-09 (fully held out)", W.date >= "2025-07-01")):
    print(" ", nm, "->", {k: (round(v, 3) if isinstance(v, float) else v)
                          for k, v in K.summarise(W[m].p, nm, W[m].r).items() if k != "strategy"})

print("\nby quarter:")
g = W.set_index("date").sort_index().groupby(pd.Grouper(freq="QE"))["p"]
print(pd.DataFrame({"n": g.size(), "avg%": g.mean(), "tot%": g.sum(),
                    "win%": g.apply(lambda x: 100 * (x > 0).mean())}).round(2).to_string())

# ------------------------------------------------------------------ trade list
STOPPX = K.STOP.replace("_bar", "_px"); TGTPX = K.TGT.replace("_bar", "_px")
W["outcome"] = K.outcome(W)
W["bars_held"] = K.bars_held(W)
cols = ["symbol", "date", "pattern", "n_base", "legout_n", "entry_plan", "entry",
        "stop", STOPPX, TGTPX, "zone_h_pct", "legout_atr", "atr_pct",
        "prev_close_pct", "dist_ema200_atr", "outcome", "bars_held", "p", "r",
        "bar", "legin_i", "base_lo_i", "base_hi_i", "legout_i", "zone_age",
        "legin_date", "base_start", "base_end", "legout_date"]
out = W[cols].rename(columns={"entry_plan": "proximal", "stop": "distal",
                              STOPPX: "stop_px", TGTPX: "target_px",
                              "p": "pnl%", "r": "R"}).sort_values("pnl%", ascending=False)
out.to_csv("trades_audit_window.csv", index=False)
print(f"\nfull trade list written: trades_audit_window.csv  ({len(out)} trades)")
print(f"outcome mix: {W.outcome.value_counts().to_dict()}   median bars held {W.bars_held.median():.0f}")

print("\n" + "=" * 112)
print("TOP 15 TRADES  (proximal = the buy limit, distal = the zone floor)")
print("=" * 112)
show = ["symbol", "date", "pattern", "n_base", "legout_n", "proximal", "distal",
        "stop_px", "target_px", "zone_h_pct", "outcome", "bars_held", "pnl%", "R"]
print(out.head(15)[show].round(2).to_string(index=False))
print("\nWORST 10")
print(out.tail(10)[show].round(2).to_string(index=False))
