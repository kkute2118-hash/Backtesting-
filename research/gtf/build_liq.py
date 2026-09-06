"""Generate every grab / sweep / run setup, with exits walked on the real path.

Exits: the structural stop is the swept extreme (that is the level the
liquidity was resting under, so a return through it says the read was
wrong), buffered by a fraction of ATR. Targets are recorded three ways so
the transcript's own target rule can be compared against fixed ones:
  liq   - the nearest untapped opposing liquidity pool
  8atr  - the fixed target used everywhere else in this research
  none  - a pure time exit at 60 bars
"""
import argparse, sqlite3, time
import numpy as np, pandas as pd
import liq as Q
from build_events import load

ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--k", type=int, default=10)
ap.add_argument("--eq", type=float, default=0.010)
ap.add_argument("--buffer", type=float, default=0.25)   # ATR below the swept extreme
ap.add_argument("--hold", type=int, default=60)
a = ap.parse_args()

con = sqlite3.connect(a.db)
syms = [r[0] for r in con.execute(
    "SELECT symbol FROM candles GROUP BY symbol HAVING COUNT(*)>=400 ORDER BY symbol")]
con.close()

rows = []; t0 = time.time()
for i, s in enumerate(syms):
    df = load(a.db, s)
    for r in Q.find_setups(df, k=a.k, eq_tol=a.eq):
        r["symbol"] = s
        rows.append(r)
    if (i + 1) % 100 == 0:
        print(f"  {i+1}/{len(syms)}  {len(rows)} setups  {time.time()-t0:.0f}s", flush=True)
d = pd.DataFrame(rows)
print(f"{len(d)} raw setups")

con = sqlite3.connect(a.db)
cols = {c: np.full(len(d), np.nan) for c in
        ("p_liq", "b_liq", "p_8atr", "b_8atr", "p_time", "b_time",
         "stop_px", "stop_pct", "rr_liq", "fwd_bars")}
how = np.empty(len(d), dtype=object)
pos = {ix: k for k, ix in enumerate(d.index)}
for sym, grp in d.groupby("symbol", sort=True):
    df = pd.read_sql_query(
        "SELECT open,high,low,close FROM candles WHERE symbol=? ORDER BY dt",
        con, params=(sym,))
    O = df["open"].to_numpy(); H = df["high"].to_numpy()
    L = df["low"].to_numpy(); C = df["close"].to_numpy()
    n = len(C)
    for ix, r in zip(grp.index, grp.itertuples()):
        j = int(r.bar); e = float(r.entry_plan); atr = float(r.atr_at_entry)
        long = r.side == "long"
        stop = (float(r.stop_struct) - a.buffer * atr if long
                else float(r.stop_struct) + a.buffer * atr)
        risk = abs(e - stop)
        if risk <= 0:
            continue
        k = pos[ix]
        cols["stop_px"][k] = stop
        cols["stop_pct"][k] = 100.0 * risk / e
        cols["fwd_bars"][k] = n - 1 - j
        tliq = float(r.target_liq)
        if np.isfinite(tliq) and ((tliq > e) if long else (tliq < e)):
            cols["rr_liq"][k] = abs(tliq - e) / risk
            p, b, h = Q.walk(O, H, L, C, j, e, stop, tliq, a.hold, long)
            cols["p_liq"][k] = p; cols["b_liq"][k] = b; how[k] = h
        t8 = e + 8 * atr if long else e - 8 * atr
        p, b, _ = Q.walk(O, H, L, C, j, e, stop, t8, a.hold, long)
        cols["p_8atr"][k] = p; cols["b_8atr"][k] = b
        p, b, _ = Q.walk(O, H, L, C, j, e, stop, None, a.hold, long)
        cols["p_time"][k] = p; cols["b_time"][k] = b
con.close()
for c, v in cols.items():
    d[c] = v
d["exit_liq"] = how
d = d[d.fwd_bars >= 20].reset_index(drop=True)     # enough path to score
print(f"{len(d)} scoreable setups")
print(d.groupby(["kind", "side"]).size())
d.to_parquet(a.out, index=False)
print(f"-> {a.out}  ({time.time()-t0:.0f}s)")
