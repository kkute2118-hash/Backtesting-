"""Ratchet stop simulator.

A schedule is a list of (trigger, new_stop) rungs. Once the running high has
touched `trigger`, the stop moves to `new_stop` and never moves back down.
Units are either percent from entry or ATR from entry.

Within a bar the stop is checked FIRST, using the level set by earlier bars,
and only then does this bar's high advance the ratchet. Intrabar order is
unknowable and that is the pessimistic reading.
"""
from __future__ import annotations
import sqlite3
import numpy as np, pandas as pd

COST = 0.23
HOLD = 60

# (name, unit, [(trigger, new_stop), ...], target)
SCHEDULES = {
    "baseline 2ATR stop, 8ATR target": ("atr", [], 8.0),
    "your plan: 5>-3, 8>0, 12>+2":     ("pct", [(5, -3), (8, 0), (12, 2)], None),
    "your plan + 8ATR target":         ("pct", [(5, -3), (8, 0), (12, 2)], 8.0),
    "later: 8>-3, 12>0, 20>+5":        ("pct", [(8, -3), (12, 0), (20, 5)], None),
    "breakeven only at +10%":          ("pct", [(10, 0)], None),
    "breakeven only at +15%":          ("pct", [(15, 0)], None),
    "atr: 2>-1, 4>0, 6>+2":            ("atr", [(2, -1), (4, 0), (6, 2)], None),
    "atr: 3>0, 6>+3":                  ("atr", [(3, 0), (6, 3)], None),
    "atr: 4>0, 8>+4":                  ("atr", [(4, 0), (8, 4)], None),
    "atr: 4>0 only":                   ("atr", [(4, 0)], None),
    "atr: 3>-1, 5>+1, 7>+3, 9>+5":     ("atr", [(3, -1), (5, 1), (7, 3), (9, 5)], None),
    "atr: 4>0, 6>+2, 8>+4, 10>+6":     ("atr", [(4, 0), (6, 2), (8, 4), (10, 6)], None),
}


def simulate(O, H, L, C, j, entry, atr, unit, rungs, target_atr, hold=HOLD,
             init_stop_atr=2.0):
    """Return (percent result, bars held, how it ended)."""
    n = len(C)
    end = min(j + hold, n - 1)
    stop = entry - init_stop_atr * atr
    tgt = entry + target_atr * atr if target_atr else None
    rung_px = [(entry * (1 + t / 100.0) if unit == "pct" else entry + t * atr,
                entry * (1 + s / 100.0) if unit == "pct" else entry + s * atr)
               for t, s in rungs]
    fired = [False] * len(rung_px)
    for k in range(j, end + 1):
        if k > j:
            if L[k] <= stop:                       # stop first, worse of level and open
                return 100.0 * (min(stop, O[k]) / entry - 1) - COST, k - j, "stop"
            if tgt and H[k] >= tgt:
                return 100.0 * (tgt / entry - 1) - COST, k - j, "target"
        else:
            if L[k] <= stop:
                return 100.0 * (stop / entry - 1) - COST, 0, "stop"
        for m, (trig, new) in enumerate(rung_px):  # this bar's high advances it
            if not fired[m] and H[k] >= trig:
                fired[m] = True
                stop = max(stop, new)
    return 100.0 * (C[end] / entry - 1) - COST, end - j, "time"


def run_all(ev, db, schedules=SCHEDULES, hold=HOLD):
    con = sqlite3.connect(db)
    names = list(schedules)
    res = {k: np.full(len(ev), np.nan) for k in names}
    bars = {k: np.full(len(ev), np.nan) for k in names}
    pos = {ix: p for p, ix in enumerate(ev.index)}
    for sym, grp in ev.groupby("symbol", sort=True):
        df = pd.read_sql_query("SELECT dt,open,high,low,close FROM candles "
                               "WHERE symbol=? ORDER BY dt", con, params=(sym,))
        O = df["open"].to_numpy(); H = df["high"].to_numpy()
        L = df["low"].to_numpy(); C = df["close"].to_numpy()
        for ix, r in zip(grp.index, grp.itertuples()):
            atr = float(r.atr_at_entry)
            if not np.isfinite(atr) or atr <= 0:
                continue
            for k in names:
                unit, rungs, tgt = schedules[k]
                p, b, _ = simulate(O, H, L, C, int(r.bar), float(r.entry_plan),
                                   atr, unit, rungs, tgt, hold)
                res[k][pos[ix]] = p; bars[k][pos[ix]] = b
    con.close()
    return res, bars


def stats(x, label):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 20:
        return {"schedule": label, "n": len(x)}
    w = x[x > 0]; l = x[x <= 0]
    return {"schedule": label, "n": len(x), "win%": round(100*len(w)/len(x), 1),
            "avg%": round(x.mean(), 2), "med%": round(float(np.median(x)), 2),
            "PF": round(w.sum()/-l.sum(), 2) if l.sum() < 0 else np.inf,
            "avg win": round(w.mean(), 1) if len(w) else np.nan,
            "avg loss": round(l.mean(), 1) if len(l) else np.nan}
