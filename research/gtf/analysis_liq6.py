"""The surviving rule used as a filter on the four strategies and on GTF.

The ask was to keep only stocks that show this behaviour and trade those.
So: tag every S1-S4 and GTF signal by whether the same symbol printed a
qualifying reversal (grab or sweep, weekly trend sharply up) in the recent
past, and split by period, because a filter that only worked in 2021-2023
is not a filter.
"""
import numpy as np, pandas as pd, sqlite3
pd.set_option("display.width", 220)
DB = ("/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c"
      "/scratchpad/data/market_data.sqlite3")

d = pd.read_parquet("/tmp/gtf/liq.parquet"); d["date"] = pd.to_datetime(d["date"])
sel = d[d.side.eq("long") & d.kind.isin(["grab", "sweep"]) & (d.weekly_slope_pct > 5)]
by_sym = {s: np.sort(g.bar.to_numpy()) for s, g in sel.groupby("symbol")}
print(f"{len(sel)} qualifying setups in {len(by_sym)} symbols")


def tagged(sym, bar, w):
    arr = by_sym.get(sym)
    if arr is None or not np.isfinite(bar): return False
    i = np.searchsorted(arr, bar, side="right") - 1
    return i >= 0 and 0 <= bar - arr[i] <= w


def split(df, flag, col, label):
    rows = []
    for lab, m in (("2021-2023", df.date < "2024-01-01"),
                   ("2024-2026", df.date >= "2024-01-01"),
                   ("last 2 years", df.date >= "2024-09-04")):
        a = df[m & flag][col]; b = df[m & ~flag][col]
        if len(a) < 50: continue
        rows.append({"what": label, "period": lab, "n kept": len(a),
                     "kept%": round(a.mean(), 2), "n dropped": len(b),
                     "dropped%": round(b.mean(), 2),
                     "difference": round(a.mean() - b.mean(), 2)})
    return rows


print("\n" + "=" * 96)
print("GTF 7/7 signals, kept only if the name swept liquidity in an uptrend recently")
print("=" * 96)
g7 = pd.read_parquet("/tmp/gtf/ratchet7.parquet"); g7["date"] = pd.to_datetime(g7["date"])
col = "p_breakeven only at +15%"
out = []
for w in (40, 120):
    f = pd.Series([tagged(s, b, w) for s, b in zip(g7.symbol, g7.bar)], index=g7.index)
    out += split(g7, f, col, f"GTF 7/7, {w}-bar window")
print(pd.DataFrame(out).to_string(index=False))

print("\n" + "=" * 96)
print("S1-S4, same filter")
print("=" * 96)
s4 = pd.read_parquet("/tmp/gtf/s1s4_exits.parquet")
s4["date"] = pd.to_datetime(s4["entry_date"])
con = sqlite3.connect(DB)
cal = pd.read_sql_query("SELECT symbol, dt FROM candles ORDER BY symbol, dt", con)
con.close()
cal["dt"] = pd.to_datetime(cal["dt"]); cal["bar"] = cal.groupby("symbol").cumcount()
s4["bar"] = (cal.set_index(["symbol", "dt"])["bar"]
             .reindex(pd.MultiIndex.from_arrays([s4.ticker, s4.date])).to_numpy())
f120 = pd.Series([tagged(s, b, 120) for s, b in zip(s4.ticker, s4.bar)], index=s4.index)
out = []
for strat in ["S1", "S2", "S3", "S4"]:
    ss = s4[s4.strategy.eq(strat)]
    out += split(ss, f120[ss.index], "p_be15", strat)
print(pd.DataFrame(out).to_string(index=False))
