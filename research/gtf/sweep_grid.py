"""Before calling the concept dead, check it is not just my parameter choice."""
import sqlite3, itertools, time
import numpy as np, pandas as pd
import sweep as S, ratchet as R
from build_events import load
pd.set_option("display.width", 240)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"

con = sqlite3.connect(DB)
syms = [r[0] for r in con.execute(
    "SELECT symbol FROM candles GROUP BY symbol HAVING COUNT(*)>=320 ORDER BY symbol")]
con.close()
cache = {s: load(DB, s) for s in syms}
print(f"{len(cache)} symbols cached")

px = {}
con = sqlite3.connect(DB)
for s in syms:
    df = pd.read_sql_query("SELECT dt,open,high,low,close FROM candles WHERE symbol=? ORDER BY dt",
                           con, params=(s,))
    px[s] = (df["open"].to_numpy(), df["high"].to_numpy(),
             df["low"].to_numpy(), df["close"].to_numpy())
con.close()

GRID = list(itertools.product([3, 5, 10],          # k, the pivot half-width
                              [1, 3, 5],           # bars allowed to reclaim
                              [1.0, 1.5, 2.0],     # min relative volume on the reclaim
                              [10, 20]))           # which EMA is retested
rows = []
t0 = time.time()
for k, rc, rv, em in GRID:
    res = []
    for s in syms:
        for r in S.find_setups(cache[s], k=k, max_reclaim_bars=rc, min_relvol=rv, ema_touch=em):
            O, H, L, C = px[s]
            p, _, _ = R.simulate(O, H, L, C, int(r["bar"]), float(r["entry_plan"]),
                                 float(r["atr_at_entry"]), "pct", [(15, 0)], None)
            res.append((r["date"], p))
    if len(res) < 200:
        continue
    df = pd.DataFrame(res, columns=["date", "p"]); df["date"] = pd.to_datetime(df.date)
    full = df.p; last2 = df.loc[df.date >= "2024-09-04", "p"]
    w = full[full > 0]; l = full[full <= 0]
    rows.append({"k": k, "reclaim<=": rc, "relvol>=": rv, "EMA": em, "n": len(df),
                 "full avg%": round(full.mean(), 2),
                 "full PF": round(w.sum()/-l.sum(), 2) if l.sum() < 0 else np.inf,
                 "last2y n": len(last2),
                 "last2y avg%": round(last2.mean(), 2) if len(last2) > 50 else np.nan})
    print(f"  k={k} rc={rc} rv={rv} ema={em}: n={len(df)} "
          f"full {full.mean():+.2f}% last2y {last2.mean():+.2f}%  [{time.time()-t0:.0f}s]", flush=True)
t = pd.DataFrame(rows)
print("\n" + "=" * 104)
print("PARAMETER GRID — sorted by the last two years")
print("=" * 104)
print(t.sort_values("last2y avg%", ascending=False).to_string(index=False))
print(f"\ngrids positive over the last 2 years: {(t['last2y avg%'] > 0).sum()} of {len(t)}")
print(f"grids positive over the full window:   {(t['full avg%'] > 0).sum()} of {len(t)}")
