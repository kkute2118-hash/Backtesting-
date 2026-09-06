import argparse, sqlite3, time
import numpy as np, pandas as pd
import sweep as S
import ratchet as R
from build_events import load

ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--k", type=int, default=5)
ap.add_argument("--reclaim", type=int, default=3)
ap.add_argument("--relvol", type=float, default=1.2)
ap.add_argument("--ema", type=int, default=20)
a = ap.parse_args()

con = sqlite3.connect(a.db)
syms = [r[0] for r in con.execute(
    "SELECT symbol FROM candles GROUP BY symbol HAVING COUNT(*)>=320 ORDER BY symbol")]
con.close()
rows = []; t0 = time.time()
for i, s in enumerate(syms):
    df = load(a.db, s)
    for r in S.find_setups(df, k=a.k, max_reclaim_bars=a.reclaim,
                           min_relvol=a.relvol, ema_touch=a.ema):
        r["symbol"] = s
        rows.append(r)
    if (i + 1) % 100 == 0:
        print(f"  {i+1}/{len(syms)}  {len(rows)} setups  {time.time()-t0:.0f}s", flush=True)
d = pd.DataFrame(rows)
print(f"{len(d)} setups")

# exits, walked on the real path, same machinery as everything else
con = sqlite3.connect(a.db)
pn = np.full(len(d), np.nan); bn = np.full(len(d), np.nan)
pb = np.full(len(d), np.nan); bb = np.full(len(d), np.nan)
pos = {ix: k for k, ix in enumerate(d.index)}
for sym, grp in d.groupby("symbol", sort=True):
    df = pd.read_sql_query("SELECT dt,open,high,low,close FROM candles WHERE symbol=? ORDER BY dt",
                           con, params=(sym,))
    O = df["open"].to_numpy(); H = df["high"].to_numpy()
    L = df["low"].to_numpy(); C = df["close"].to_numpy()
    for ix, r in zip(grp.index, grp.itertuples()):
        p, b, _ = R.simulate(O, H, L, C, int(r.bar), float(r.entry_plan), float(r.atr_at_entry),
                             "atr", [], 8.0)
        pn[pos[ix]] = p; bn[pos[ix]] = b
        p2, b2, _ = R.simulate(O, H, L, C, int(r.bar), float(r.entry_plan), float(r.atr_at_entry),
                               "pct", [(15, 0)], None)
        pb[pos[ix]] = p2; bb[pos[ix]] = b2
con.close()
d["p_8atr"] = pn; d["b_8atr"] = bn; d["p_be15"] = pb; d["b_be15"] = bb
d.to_parquet(a.out, index=False)
print(f"-> {a.out}  ({time.time()-t0:.0f}s)")
