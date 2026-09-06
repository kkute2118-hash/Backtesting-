"""Phase 22/23/24/34: try to break the winner."""
import numpy as np, pandas as pd
import candidates as K
pd.set_option("display.width", 250)

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
c = pd.read_parquet("/tmp/gtf/control.parquet"); c["date"] = pd.to_datetime(c["date"])
d = d[d.gap_through == 0].copy(); d["p"] = K.pct_pnl(d); d["r"] = K.r_pnl(d)
c = c.copy(); c["p"] = K.pct_pnl(c)
TR = d[d.date < "2024-04-01"]
q = lambda f, p: float(np.nanpercentile(TR[f], p))
TH = dict(atr=q("atr_pct", 50), legout=q("legout_atr", 50),
          risk=q("risk_pct", 40), speed=q("prev_close_pct", 50))

def C12(x, atr=None, legout=None, risk=None, speed=None, ema=0.96):
    return (x.risk_pct.ge(TH["risk"] if risk is None else risk)
            & x.legout_atr.ge(TH["legout"] if legout is None else legout)
            & x.atr_pct.ge(TH["atr"] if atr is None else atr)
            & x.prev_close_pct.ge(TH["speed"] if speed is None else speed)
            & x.dist_ema200_atr.le(ema))

W = d[C12(d)]
print(f"C12 total trades {len(W)}, {W.symbol.nunique()} symbols, "
      f"{W.date.min().date()} .. {W.date.max().date()}\n")

# ---------------------------------------------------------------- Phase 22
print("=" * 118)
print("PARAMETER SENSITIVITY - is this a plateau or a spike? (whole sample, avg % per trade)")
print("=" * 118)
for pname, grid in (("ema200 cut (ATR)", [0.4, 0.6, 0.8, 0.96, 1.2, 1.6, 2.0, 3.0, 99]),
                    ("atr_pct floor", [2.0, 2.6, 3.24, 3.8, 4.5, 5.5]),
                    ("legout_atr floor", [0.3, 0.6, 0.837, 1.1, 1.5, 2.0]),
                    ("risk_pct floor", [1.2, 1.8, 2.21, 2.8, 3.5, 4.5]),
                    ("approach-speed floor", [0.3, 0.8, 1.19, 1.6, 2.2, 3.0])):
    row = []
    for g in grid:
        kw = {"ema": g} if "ema" in pname else \
             {"atr": g} if "atr_pct" in pname else \
             {"legout": g} if "legout" in pname else \
             {"risk": g} if "risk_pct" in pname else {"speed": g}
        s = d[C12(d, **kw)]
        row.append((g, len(s), np.nanmean(s.p)))
    print(f"{pname:22s} " + "  ".join(f"{g:>5}:{v:+.2f}(n={n})" for g, n, v in row))

# ---------------------------------------------------------------- Phase 21
print("\n" + "=" * 118)
print("WALK-FORWARD - six-month windows, no refitting (thresholds are fixed from train)")
print("=" * 118)
wf = W.set_index("date").sort_index()
g = wf.groupby(pd.Grouper(freq="2QE"))["p"]
tab = pd.DataFrame({"n": g.size(), "avg%": g.mean(), "tot%": g.sum(),
                    "win%": g.apply(lambda x: 100 * (x > 0).mean())}).round(2)
print(tab.to_string())
print(f"\nwindows positive: {(tab['avg%'] > 0).sum()}/{len(tab)}")

# ---------------------------------------------------------------- Phase 23
print("\n" + "=" * 118)
print("CROSS-STOCK CONCENTRATION")
print("=" * 118)
bs = W.groupby("symbol")["p"].agg(["size", "sum", "mean"]).sort_values("sum", ascending=False)
pos = bs[bs["sum"] > 0]["sum"].sum()
print(f"symbols traded            {len(bs)}")
print(f"symbols profitable        {100*(bs['sum']>0).mean():.1f}%")
print(f"median symbol total %     {bs['sum'].median():.2f}")
print(f"median symbol avg %       {bs['mean'].median():.2f}")
print(f"top 5 share of gross win  {100*bs['sum'].head(5).sum()/pos:.1f}%")
print(f"top 20 share of gross win {100*bs['sum'].head(20).sum()/pos:.1f}%")
print("\nresult with the 10 best symbols removed entirely:")
drop = set(bs.head(10).index)
w2 = W[~W.symbol.isin(drop)]
print(" ", K.summarise(w2.p, "C12 minus top-10 symbols"))

# ---------------------------------------------------------------- Phase 24
print("\n" + "=" * 118)
print("MARKET REGIME - equal-weight index of the stored universe")
print("=" * 118)
import sqlite3
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"
con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt, symbol, close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()
idx.name = "mkt"
mk = pd.DataFrame({"mkt": idx})
mk["ma50"] = mk.mkt.rolling(50).mean()
mk["fwd"] = mk.mkt.pct_change(20).shift(-20) * 100
mk["r20"] = mk.mkt.pct_change(20) * 100
mk["vol"] = mk.mkt.pct_change().rolling(20).std() * np.sqrt(252) * 100
def regime(row):
    if not np.isfinite(row.r20) or not np.isfinite(row.ma50):
        return "n/a"
    up = row.mkt > row.ma50
    if row.r20 > 6:  return "strong bull"
    if row.r20 < -6: return "bear"
    return "bull" if up else "sideways/recovery"
mk["regime"] = mk.apply(regime, axis=1)
mk["volregime"] = np.where(mk.vol > mk.vol.median(), "high vol", "low vol")
W2 = W.merge(mk[["regime", "volregime"]], left_on="date", right_index=True, how="left")
allm = d.merge(mk[["regime", "volregime"]], left_on="date", right_index=True, how="left")
print(pd.DataFrame({
    "C12 n": W2.groupby("regime").size(),
    "C12 avg%": W2.groupby("regime")["p"].mean(),
    "all-arrivals avg%": allm.groupby("regime")["p"].mean(),
}).round(3).to_string())
print()
print(pd.DataFrame({
    "C12 n": W2.groupby("volregime").size(),
    "C12 avg%": W2.groupby("volregime")["p"].mean(),
    "all-arrivals avg%": allm.groupby("volregime")["p"].mean(),
}).round(3).to_string())

# ---------------------------------------------------------------- placebo for C12
print("\n" + "=" * 118)
print("PLACEBO for the winner - same months, same symbols, same risk, random bar")
print("=" * 118)
key = W[["symbol", "date"]].copy(); key["m"] = key.date.dt.to_period("M")
cc = c.copy(); cc["m"] = cc.date.dt.to_period("M")
sel = cc.merge(key[["symbol", "m"]].drop_duplicates(), on=["symbol", "m"], how="inner")
print(" C12      ", K.summarise(W.p, "C12"))
print(" placebo  ", K.summarise(sel.p, "matched placebo"))
lo, hi = K.block_boot(W.date, W.p.to_numpy())
print(f"\n C12 month-block bootstrap 95% CI on mean %: [{lo:+.3f}, {hi:+.3f}]")
lo2, hi2 = K.block_boot(sel.date, sel.p.to_numpy())
print(f" placebo                            95% CI: [{lo2:+.3f}, {hi2:+.3f}]")
