"""A matched placebo for the GTF events.

The 2021-2026 Indian market went nearly straight up, so a long-only dip-buying
rule can look excellent while carrying no information at all. For every real
arrival this draws a control trade in the same symbol, in the same calendar
month, at a random bar, with the same planned risk in percent - identical
geometry, identical regime, no zone. Anything the real events earn above this
is what the demand zone is actually worth.
"""
import argparse, sqlite3, time
import numpy as np, pandas as pd
import gtfcore as G
from build_events import (load, R_GRID, PCT_GRID, HORIZONS, MAX_HOLD,
                          STOP_K, STOP_M, TGT_ATR, _first_break)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--events", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20260906)
    a = ap.parse_args()

    ev = pd.read_parquet(a.events)
    ev["date"] = pd.to_datetime(ev["date"])
    rng = np.random.default_rng(a.seed)
    rows = []
    t0 = time.time()
    for si, (sym, grp) in enumerate(ev.groupby("symbol", sort=True)):
        df = load(a.db, sym)
        n = len(df)
        O = df["open"].to_numpy(); H = df["high"].to_numpy()
        L = df["low"].to_numpy(); C = df["close"].to_numpy()
        A = G.atr(H, L, C, 14)
        dates = df.index
        month = np.asarray(dates.to_period("M"))
        pos = np.arange(n)
        for _, e in grp.iterrows():
            # a random bar in the same month, so regime is held fixed
            pool = np.nonzero((month == pd.Period(e["date"], "M"))
                              & (pos > 0) & (pos + 20 < n))[0]
            if not len(pool):
                continue
            j = int(rng.choice(pool))
            # same planned risk, entered on that bar's close
            entry = C[j]
            risk = entry * e["risk_pct"] / 100.0
            stop = entry - risk
            end = min(j + MAX_HOLD, n - 1)
            fh = H[j + 1:end + 1]; fl = L[j + 1:end + 1]
            fo = O[j + 1:end + 1]; fc = C[j + 1:end + 1]
            if len(fc) < 21:
                continue
            run_max = np.maximum.accumulate(fh); run_min = np.minimum.accumulate(fl)
            atr_j = A[j]
            if not np.isfinite(atr_j) or atr_j <= 0:
                continue
            r = {"symbol": sym, "date": dates[j], "entry": entry,
                 "entry_plan": entry, "stop": stop,
                 "risk_pct": float(e["risk_pct"]), "gap_through": 0,
                 "atr_at_entry": float(atr_j), "atr_pct": 100.0 * atr_j / entry}
            # identical stop/target grid to the real events, so the two are
            # scored by exactly the same machinery
            for K in STOP_K:
                lv = stop - K * atr_j
                r[f"sK{K}_bar"] = _first_break(L, fl, j, lv); r[f"sK{K}_px"] = lv
            for M in STOP_M:
                lv = entry - M * atr_j
                r[f"sM{M}_bar"] = _first_break(L, fl, j, lv); r[f"sM{M}_px"] = lv
            for M in TGT_ATR:
                lv = entry + M * atr_j
                hh = np.nonzero(run_max >= lv)[0]
                r[f"gA{M}_bar"] = int(hh[0]) + 1 if len(hh) else -1
                r[f"gA{M}_px"] = lv
            hits = np.nonzero(fl <= stop)[0]
            sb = int(hits[0]) + 1 if len(hits) else -1
            r["stop_bar"] = sb
            r["stop_fill"] = float(min(stop, fo[sb - 1])) if sb > 0 else np.nan
            for rm in R_GRID:
                hh = np.nonzero(run_max >= entry + rm * risk)[0]
                r[f"t{rm}R_bar"] = int(hh[0]) + 1 if len(hh) else -1
            for p in PCT_GRID:
                hh = np.nonzero(run_max >= entry * (1 + p / 100.0))[0]
                r[f"t{p}pct_bar"] = int(hh[0]) + 1 if len(hh) else -1
            for hzn in HORIZONS:
                k = min(hzn - 1, len(fc) - 1)
                r[f"mfe{hzn}"] = 100.0 * (run_max[k] / entry - 1.0)
                r[f"mae{hzn}"] = 100.0 * (run_min[k] / entry - 1.0)
                r[f"ret{hzn}"] = 100.0 * (fc[k] / entry - 1.0)
            rows.append(r)
        if (si + 1) % 50 == 0:
            print(f"  {si+1} symbols  {len(rows)} controls  {time.time()-t0:.0f}s", flush=True)
    out = pd.DataFrame(rows)
    out.to_parquet(a.out, index=False)
    print(f"{len(out)} controls -> {a.out}")

if __name__ == "__main__":
    main()
