"""Where should a ratchet stop sit? Ask the paths, do not guess.

For every trade, walk the real path and record: once price has reached +X, what
happens afterwards - how much does it give back, and how often does it go on to
a much bigger number? A ratchet is only worth having where the give-back is
larger than the upside you forfeit by being stopped out of it.
"""
import argparse, sqlite3, time
import numpy as np, pandas as pd
import gtfcore as G
pd.set_option("display.width", 220)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"
HOLD = 60
RUNGS_PCT = [3, 5, 8, 10, 12, 15, 20, 25, 30]
RUNGS_ATR = [1, 2, 3, 4, 5, 6, 8]

ev = pd.read_parquet("/tmp/gtf/events.parquet")
ev["date"] = pd.to_datetime(ev["date"])
ev = ev[(ev.gap_through == 0) & ev.score.eq(7.0) & ev.turnover_cr.ge(10)]
print(f"studying {len(ev)} 7/7 trades\n")

con = sqlite3.connect(DB)
rows = []
t0 = time.time()
for sym, grp in ev.groupby("symbol", sort=True):
    df = pd.read_sql_query("SELECT dt,open,high,low,close FROM candles WHERE symbol=? ORDER BY dt",
                           con, params=(sym,))
    O = df["open"].to_numpy(); H = df["high"].to_numpy()
    L = df["low"].to_numpy(); C = df["close"].to_numpy(); n = len(C)
    for r in grp.itertuples():
        j = int(r.bar); e = float(r.entry_plan); atr = float(r.atr_at_entry)
        if not np.isfinite(atr) or atr <= 0: continue
        end = min(j + HOLD, n - 1)
        if end <= j: continue
        hi = (H[j + 1:end + 1] / e - 1) * 100          # path in percent from entry
        lo = (L[j + 1:end + 1] / e - 1) * 100
        if not len(hi): continue
        run_hi = np.maximum.accumulate(hi)
        rec = {"symbol": sym, "date": r.date, "atr_pct": 100 * atr / e,
               "final_mfe": run_hi[-1], "final_ret": (C[end] / e - 1) * 100}
        for X in RUNGS_PCT:
            k = np.nonzero(run_hi >= X)[0]
            if len(k):
                k0 = int(k[0])
                rec[f"hit{X}"] = 1
                rec[f"after{X}_min"] = float(lo[k0:].min())      # worst point after
                rec[f"after{X}_max"] = float(hi[k0:].max())      # best point after
                rec[f"after{X}_end"] = float((C[end] / e - 1) * 100)
            else:
                rec[f"hit{X}"] = 0
        for M in RUNGS_ATR:
            X = M * 100 * atr / e
            k = np.nonzero(run_hi >= X)[0]
            rec[f"hitA{M}"] = 1 if len(k) else 0
            if len(k):
                k0 = int(k[0])
                rec[f"afterA{M}_min"] = float(lo[k0:].min())
                rec[f"afterA{M}_max"] = float(hi[k0:].max())
        rows.append(rec)
con.close()
P = pd.DataFrame(rows)
print(f"built {len(P)} paths in {time.time()-t0:.0f}s\n")
P.to_parquet("/tmp/gtf/paths7.parquet", index=False)

print("=" * 112)
print("ONCE A TRADE HAS REACHED +X%, WHAT HAPPENS NEXT?")
print("=" * 112)
out = []
for X in RUNGS_PCT:
    s = P[P[f"hit{X}"] == 1]
    if len(s) < 40: continue
    give = s[f"after{X}_min"]
    out.append({
        "reached": f"+{X}%",
        "share of trades": round(100 * len(s) / len(P), 1),
        "n": len(s),
        "median worst point after": round(give.median(), 1),
        "25% of them fall below": round(give.quantile(0.25), 1),
        "share giving back to 0%": round(100 * (give <= 0).mean(), 1),
        "share giving back to -3%": round(100 * (give <= -3).mean(), 1),
        "median best point after": round(s[f"after{X}_max"].median(), 1),
        "share going on to +25%": round(100 * (s[f"after{X}_max"] >= 25).mean(), 1),
    })
print(pd.DataFrame(out).to_string(index=False))

print("\n" + "=" * 112)
print("SAME, IN ATR - because a fixed percentage means different things in")
print("a 3%-a-day stock and a 7%-a-day stock")
print("=" * 112)
out = []
for M in RUNGS_ATR:
    s = P[P[f"hitA{M}"] == 1]
    if len(s) < 40: continue
    # express give-back in ATR too
    g = s[f"afterA{M}_min"] / s.atr_pct
    b = s[f"afterA{M}_max"] / s.atr_pct
    out.append({"reached": f"+{M} ATR", "share": round(100*len(s)/len(P), 1), "n": len(s),
                "median give-back (ATR)": round(g.median(), 2),
                "share falling back below entry": round(100 * (g <= 0).mean(), 1),
                "share falling back below -1 ATR": round(100 * (g <= -1).mean(), 1),
                "median best after (ATR)": round(b.median(), 2),
                "share reaching +8 ATR": round(100 * (b >= 8).mean(), 1)})
print(pd.DataFrame(out).to_string(index=False))
