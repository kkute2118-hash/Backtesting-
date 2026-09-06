"""Liquidity patterns as a FILTER on the existing strategies.

The run's placebo is the finding that matters. Random entries in the same
stock in the same month as a liquidity run returned +9.9%, while taking the
run itself returned +4.6%. The run picks a very good stock and then enters
it at a very bad moment. So the run is worth testing as a universe filter -
name selection - rather than as a timing signal, with the timing left to
the setups we already trust.
"""
import numpy as np, pandas as pd
pd.set_option("display.width", 250)

d = pd.read_parquet("/tmp/gtf/liq.parquet"); d["date"] = pd.to_datetime(d["date"])
c = pd.read_parquet("/tmp/gtf/liq_control.parquet")
CUT = "2024-09-04"

runs = d[d.kind.eq("run") & d.side.eq("long")]
by_sym = {s: np.sort(g.bar.to_numpy()) for s, g in runs.groupby("symbol")}


def recent_run(sym, bar, window):
    arr = by_sym.get(sym)
    if arr is None or not np.isfinite(bar):
        return False
    i = np.searchsorted(arr, bar, side="right") - 1
    return i >= 0 and 0 < bar - arr[i] <= window


def st(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 30: return {"n": len(x)}
    w = x[x > 0]; l = x[x <= 0]
    return {"n": len(x), "win%": round(100 * len(w) / len(x), 1),
            "avg%": round(float(x.mean()), 2),
            "PF": round(w.sum() / -l.sum(), 2) if l.sum() < 0 else np.inf}


print("=" * 112)
print("A. REVERSAL SETUPS THAT FOLLOW A RUN IN THE SAME NAME")
print("   run = the stock proved it can take liquidity and keep going")
print("   grab/sweep = the pullback that gives a price")
print("=" * 112)
rev = d[d.side.eq("long") & d.kind.isin(["grab", "sweep"])].copy()
for w in (20, 40, 60, 120):
    rev[f"run{w}"] = [recent_run(s, b, w) for s, b in zip(rev.symbol, rev.bar)]
rows = []
for w in (20, 40, 60, 120):
    for v, lab in ((True, "after a run"), (False, "no recent run")):
        g = rev[rev[f"run{w}"].eq(v)]
        rows.append({"window": f"{w} bars", "group": lab, **st(g.p_time),
                     "last2y n": int((g.date >= CUT).sum()),
                     "last2y%": round(g.loc[g.date >= CUT, "p_time"].mean(), 2)})
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 112)
print("B. THE SAME FILTER ON THE GTF 7/7 SIGNALS")
print("=" * 112)
g7 = pd.read_parquet("/tmp/gtf/ratchet7.parquet"); g7["date"] = pd.to_datetime(g7["date"])
col = "p_breakeven only at +15%"
for w in (20, 40, 60, 120):
    g7[f"run{w}"] = [recent_run(s, b, w) for s, b in zip(g7.symbol, g7.bar)]
rows = []
for w in (20, 40, 60, 120):
    for v, lab in ((True, "after a run"), (False, "no recent run")):
        g = g7[g7[f"run{w}"].eq(v)]
        rows.append({"window": f"{w} bars", "group": lab, **st(g[col]),
                     "last2y%": round(g.loc[g.date >= CUT, col].mean(), 2)
                     if (g.date >= CUT).sum() >= 30 else np.nan})
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 112)
print("C. AND ON S1-S4")
print("=" * 112)
s4 = pd.read_parquet("/tmp/gtf/s1s4_exits.parquet")
s4["date"] = pd.to_datetime(s4["entry_date"])
# s1s4 rows carry no bar index; map date -> bar position per symbol
import sqlite3
DB = ("/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c"
      "/scratchpad/data/market_data.sqlite3")
con = sqlite3.connect(DB)
cal = pd.read_sql_query("SELECT symbol, dt FROM candles ORDER BY symbol, dt", con)
con.close()
cal["dt"] = pd.to_datetime(cal["dt"])
cal["bar"] = cal.groupby("symbol").cumcount()
key = cal.set_index(["symbol", "dt"])["bar"]
s4["bar"] = key.reindex(pd.MultiIndex.from_arrays([s4.ticker, s4.date])).to_numpy()
print(f"mapped {s4.bar.notna().sum()}/{len(s4)} S1-S4 signals to a bar index")
for w in (40, 60, 120):
    s4[f"run{w}"] = [recent_run(s, b, w) for s, b in zip(s4.ticker, s4.bar)]
rows = []
for strat in ["S1", "S2", "S3", "S4"]:
    ss = s4[s4.strategy.eq(strat)]
    for w in (40, 60, 120):
        for v, lab in ((True, "after run"), (False, "no run")):
            g = ss[ss[f"run{w}"].eq(v)]
            rows.append({"strategy": strat, "window": w, "group": lab, **st(g["p_be15"])})
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 112)
print("D. DOES THE S1-S4 RUN FILTER HOLD UP OUT OF SAMPLE?")
print("   It shows up on S1/S3/S4 but not on GTF or on the reversal setups")
print("   themselves, which is exactly the shape a regime artefact takes.")
print("=" * 112)
rows = []
for strat in ["S1", "S2", "S3", "S4"]:
    ss = s4[s4.strategy.eq(strat)]
    for lab, m in (("2021-2023", ss.date < "2024-01-01"),
                   ("2024", (ss.date >= "2024-01-01") & (ss.date < "2025-01-01")),
                   ("2025+", ss.date >= "2025-01-01"),
                   ("last 2 years", ss.date >= CUT)):
        a = ss[m & ss["run120"].eq(True)]["p_be15"]
        b = ss[m & ss["run120"].eq(False)]["p_be15"]
        if len(a) < 100 or len(b) < 100: continue
        rows.append({"strategy": strat, "period": lab, "n after run": len(a),
                     "after run%": round(a.mean(), 2), "n no run": len(b),
                     "no run%": round(b.mean(), 2),
                     "difference": round(a.mean() - b.mean(), 2)})
print(pd.DataFrame(rows).to_string(index=False))

print("\nsame, for the GTF 7/7 signals:")
rows = []
for lab, m in (("2021-2023", g7.date < "2024-01-01"),
               ("2024", (g7.date >= "2024-01-01") & (g7.date < "2025-01-01")),
               ("2025+", g7.date >= "2025-01-01")):
    a = g7[m & g7["run120"].eq(True)][col]; b = g7[m & g7["run120"].eq(False)][col]
    if len(a) < 60 or len(b) < 60: continue
    rows.append({"period": lab, "n after run": len(a), "after run%": round(a.mean(), 2),
                 "n no run": len(b), "no run%": round(b.mean(), 2),
                 "difference": round(a.mean() - b.mean(), 2)})
print(pd.DataFrame(rows).to_string(index=False))
