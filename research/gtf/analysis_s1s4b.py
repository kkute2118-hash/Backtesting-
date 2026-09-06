"""If the score cannot rank S1-S4 signals, what can? Strategy identity, and
the exit - which the audit already flagged as badly matched to the excursions."""
import numpy as np, pandas as pd, sqlite3
import ratchet as R
pd.set_option("display.width", 250)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"
import gtfcore as G

d = pd.read_parquet("/tmp/gtf/s1s4.parquet")
d["date"] = pd.to_datetime(d["signal_date"]); d["edate"] = pd.to_datetime(d["entry_date"])
d["y"] = d.r_multiple.astype(float)
print("=" * 104)
print("PER STRATEGY, with the engine's own exit (7% stop, 3R target, 60-bar cap)")
print("=" * 104)
for nm, m in (("full window", pd.Series(True, index=d.index)),
              ("last 2 years", d.date >= "2024-09-04")):
    g = d[m].groupby("strategy").agg(
        n=("y", "size"), win=("y", lambda s: 100*(s > 0).mean()),
        avgR=("y", "mean"), totR=("y", "sum"),
        avg_pct=("return_pct", "mean"), mfe=("mfe_pct", "mean"), mae=("mae_pct", "mean"))
    g["PF"] = d[m].groupby("strategy")["y"].apply(
        lambda s: s[s > 0].sum() / -s[s <= 0].sum() if (s <= 0).any() else np.inf)
    print(f"\n{nm}"); print(g.round(3).to_string())

# ------------------------------------------------------------------ better exit
print("\n" + "=" * 104)
print("THE SAME SIGNALS WITH THE GTF EXIT (stop entry-2ATR, target entry+8ATR)")
print("=" * 104)
con = sqlite3.connect(DB)
d["p_new"] = np.nan; d["b_new"] = np.nan; d["p_be15"] = np.nan; d["b_be15"] = np.nan
d["atr_at_entry"] = np.nan
pos = {ix: k for k, ix in enumerate(d.index)}
pn = np.full(len(d), np.nan); bn = np.full(len(d), np.nan)
pb = np.full(len(d), np.nan); bb = np.full(len(d), np.nan)
av = np.full(len(d), np.nan)
for sym, grp in d.groupby("ticker", sort=True):
    df = pd.read_sql_query("SELECT dt,open,high,low,close FROM candles WHERE symbol=? ORDER BY dt",
                           con, params=(sym,))
    if df.empty: continue
    dts = pd.to_datetime(df["dt"]).to_numpy()
    O = df["open"].to_numpy(); H = df["high"].to_numpy()
    L = df["low"].to_numpy(); C = df["close"].to_numpy()
    A = G.atr(H, L, C, 14)
    imap = {v: i for i, v in enumerate(dts)}
    for ix, r in zip(grp.index, grp.itertuples()):
        j = imap.get(np.datetime64(r.edate))
        if j is None or j < 1 or j + 5 >= len(C): continue
        atr = A[j - 1]
        if not np.isfinite(atr) or atr <= 0: continue
        e = float(r.entry)
        p, b, _ = R.simulate(O, H, L, C, j, e, atr, "atr", [], 8.0)
        pn[pos[ix]] = p; bn[pos[ix]] = b
        p2, b2, _ = R.simulate(O, H, L, C, j, e, atr, "pct", [(15, 0)], None)
        pb[pos[ix]] = p2; bb[pos[ix]] = b2
        av[pos[ix]] = atr
con.close()
d["p_new"] = pn; d["b_new"] = bn; d["p_be15"] = pb; d["b_be15"] = bb; d["atr_at_entry"] = av
d["p_old"] = d.return_pct.astype(float)

for nm, m in (("full window", d.p_new.notna()),
              ("last 2 years", d.p_new.notna() & (d.date >= "2024-09-04"))):
    rows = []
    for col, lab in (("p_old", "engine exit: 7% stop / 3R"),
                     ("p_new", "GTF exit: 2ATR stop / 8ATR"),
                     ("p_be15", "2ATR stop / breakeven at +15%")):
        for s in ["S1", "S2", "S3", "S4"]:
            x = d.loc[m & d.strategy.eq(s), col].dropna()
            if len(x) < 50: continue
            w = x[x > 0]; l = x[x <= 0]
            rows.append({"exit": lab, "strategy": s, "n": len(x),
                         "win%": round(100*len(w)/len(x), 1), "avg%": round(x.mean(), 2),
                         "PF": round(w.sum()/-l.sum(), 2) if l.sum() < 0 else np.inf})
    print(f"\n{nm}")
    print(pd.DataFrame(rows).pivot_table(index="strategy", columns="exit",
                                         values=["avg%", "PF", "win%"], sort=False).round(2).to_string())
d.to_parquet("/tmp/gtf/s1s4_exits.parquet", index=False)
print("\nsaved /tmp/gtf/s1s4_exits.parquet")
