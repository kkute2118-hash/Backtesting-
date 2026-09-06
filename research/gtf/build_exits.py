"""Walk each trade's actual forward path under several exit policies.

The fixed +4 ATR target was chosen from a grid of static targets, but average
favourable excursion over 60 bars is +21%, so a static target is leaving the
tail on the table. This walks the real path bar by bar so trailing stops,
breakeven moves and partial exits can be compared on identical trades.

Within a bar the stop is checked before the target, and the trailing level used
is the one set by bars strictly before it. Both choices are the pessimistic
ones; intrabar order is unknowable and the optimistic reading is how a backtest
flatters itself.
"""
from __future__ import annotations
import argparse, sqlite3, time
import numpy as np, pandas as pd
import gtfcore as G

COST = 0.23
HOLD = 60

# name -> (init_stop_atr, target_atr or None, trail_atr or None,
#          breakeven_at_atr or None, partial_at_atr or None, partial_frac)
POLICIES = {
    "fix_2_4":        (2.0, 4.0,  None, None, None, 0.0),
    "fix_2_6":        (2.0, 6.0,  None, None, None, 0.0),
    "fix_2_8":        (2.0, 8.0,  None, None, None, 0.0),
    "trail_2_2":      (2.0, None, 2.0,  None, None, 0.0),
    "trail_2_3":      (2.0, None, 3.0,  None, None, 0.0),
    "trail_2_4":      (2.0, None, 4.0,  None, None, 0.0),
    "be2_trail3":     (2.0, None, 3.0,  2.0,  None, 0.0),
    "be2_trail4":     (2.0, None, 4.0,  2.0,  None, 0.0),
    "half2_trail3":   (2.0, None, 3.0,  None, 2.0,  0.5),
    "half2_trail4":   (2.0, None, 4.0,  None, 2.0,  0.5),
    "half3_trail4":   (2.0, None, 4.0,  None, 3.0,  0.5),
    "half2_be_tr3":   (2.0, None, 3.0,  2.0,  2.0,  0.5),
}


def run_one(O, H, L, C, j, entry, atr, n, hold=HOLD):
    """Return {policy: realised percent} for one trade."""
    out = {}
    end = min(j + hold, n - 1)
    for name, (s0, tgt, trail, be, part, pfrac) in POLICIES.items():
        stop = entry - s0 * atr
        target = entry + tgt * atr if tgt else None
        peak = entry
        booked = 0.0          # percent already realised on the partial
        rem = 1.0
        done = False
        exit_px = None
        moved_be = False
        took_part = False
        for k in range(j, end + 1):
            if k > j:                       # the entry bar cannot pay us
                # 1. stop first, filled at the worse of the level and the open
                if L[k] <= stop:
                    exit_px = min(stop, O[k])
                    done = True
                    break
                # 2. partial
                if part and not took_part and H[k] >= entry + part * atr:
                    booked += pfrac * 100.0 * ((entry + part * atr) / entry - 1.0)
                    rem -= pfrac
                    took_part = True
                # 3. full target
                if target and H[k] >= target:
                    exit_px = target
                    done = True
                    break
                # 4. breakeven move
                if be and not moved_be and H[k] >= entry + be * atr:
                    stop = max(stop, entry)
                    moved_be = True
                # 5. trail, using this bar's high for the NEXT bar's level
                if trail:
                    peak = max(peak, H[k])
                    stop = max(stop, peak - trail * atr)
            else:
                if L[k] <= stop:            # stopped on the entry bar
                    exit_px = stop
                    done = True
                    break
                if trail:
                    peak = max(peak, H[k])
                    stop = max(stop, peak - trail * atr)
        if exit_px is None:
            exit_px = C[end]                # time stop
        out[name] = booked + rem * 100.0 * (exit_px / entry - 1.0) - COST
        out[name + "__bars"] = float((k if done else end) - j)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--events", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ev = pd.read_parquet(a.events)
    con = sqlite3.connect(a.db)
    names = list(POLICIES)
    cols = [f"x_{k}" for k in names] + [f"b_{k}" for k in names]
    rows = np.full((len(ev), len(cols)), np.nan)
    t0 = time.time()
    for si, (sym, grp) in enumerate(ev.groupby("symbol", sort=True)):
        df = pd.read_sql_query("SELECT dt,open,high,low,close FROM candles "
                               "WHERE symbol=? ORDER BY dt", con, params=(sym,))
        O = df["open"].to_numpy(); H = df["high"].to_numpy()
        L = df["low"].to_numpy(); C = df["close"].to_numpy(); n = len(C)
        # the control carries no bar index, so derive it from the date
        bmap = {v: i for i, v in enumerate(pd.to_datetime(df["dt"]).to_numpy())}
        for pos, r in zip(grp.index, grp.itertuples()):
            if not hasattr(r, "bar"):
                b = bmap.get(np.datetime64(r.date))
                if b is None:
                    continue
                r = r._replace(**{}) if False else r
                bar_i = int(b)
            else:
                bar_i = int(r.bar)
            if not np.isfinite(r.atr_at_entry) or r.atr_at_entry <= 0:
                continue
            res = run_one(O, H, L, C, bar_i, float(r.entry),
                          float(r.atr_at_entry), n)
            rows[ev.index.get_loc(pos)] = ([res[k] for k in names]
                                           + [res[k + "__bars"] for k in names])
        if (si + 1) % 100 == 0:
            print(f"  {si+1} symbols  {time.time()-t0:.0f}s", flush=True)
    con.close()
    out = pd.DataFrame(rows, columns=cols, index=ev.index)
    keep = ["symbol", "date"] + (["bar"] if "bar" in ev.columns else [])
    pd.concat([ev[keep].reset_index(drop=True), out.reset_index(drop=True)],
              axis=1).to_parquet(a.out, index=False)
    print(f"{len(out)} rows -> {a.out}  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
