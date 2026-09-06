"""Liquidity sweep -> reclaim -> EMA retest.

The setup, as described:
  1. price takes out a prior daily swing low (the sweep - stops get run)
  2. the weekly trend is sharply up, so this is a shakeout inside an uptrend
  3. it bounces back above that low quickly, on good volume (the reclaim)
  4. it then retests the 10/20 EMA on the daily, and that retest is the entry

Every step below uses only bars up to and including its own index. A swing low
is only usable once it has been CONFIRMED, which takes `k` bars after the fact -
that delay is real and is respected here.
"""
from __future__ import annotations
import numpy as np, pandas as pd
import gtfcore as G


def swing_lows(L, k):
    """Indices of pivot lows, paired with the bar they become known on.

    low[p] is a pivot if it is the lowest of the 2k+1 bars centred on it. It is
    not knowable until p+k, so that is the bar from which it may be used.
    """
    n = len(L)
    out = []
    for p in range(k, n - k):
        w = L[p - k:p + k + 1]
        if L[p] == w.min() and (w[:k] > L[p]).all() and (w[k + 1:] > L[p]).all():
            out.append((p, p + k))
    return out


def find_setups(df, k=5, max_reclaim_bars=3, min_relvol=1.2, max_retest_bars=15,
                ema_touch=20, weekly_slope_min=0.0, sweep_max_depth_atr=3.0):
    """Yield one dict per completed setup. Entry is the close of the retest bar."""
    O = df["open"].to_numpy(); H = df["high"].to_numpy()
    L = df["low"].to_numpy(); C = df["close"].to_numpy(); V = df["volume"].to_numpy()
    n = len(C)
    if n < 300:
        return []
    A = G.atr(H, L, C, 14)
    e10 = G.ema(C, 10); e20 = G.ema(C, 20); e50 = G.ema(C, 50); e200 = G.ema(C, 200)
    v20 = pd.Series(V).rolling(20, min_periods=20).mean().to_numpy()
    rsi = G.rsi(C, 14)

    wb, _, wlast = G.aggregate(df, "W")
    wc = wb["close"].to_numpy()
    w_sma = G.sma(wc, 20)                      # 20-week trend, ~1 quarter
    w_slope = np.full(len(wc), np.nan)
    w_slope[6:] = (w_sma[6:] / w_sma[:-6] - 1) * 100      # % over 6 weeks

    ema_arr = e10 if ema_touch == 10 else e20
    pivots = swing_lows(L, k)
    out = []
    for p, known in pivots:
        lvl = L[p]
        # 1. the sweep: first bar after the pivot is confirmed that trades below it
        s = None
        for i in range(known + 1, min(n, known + 60)):
            if L[i] < lvl:
                s = i
                break
            if C[i] > lvl * 1.25:              # ran away without sweeping
                break
        if s is None:
            continue
        if not np.isfinite(A[s]) or A[s] <= 0:
            continue
        if (lvl - L[s]) / A[s] > sweep_max_depth_atr:      # a collapse, not a sweep
            continue
        # 2. the reclaim: back above the swept low within a few bars, on volume
        r = None
        for i in range(s, min(n, s + max_reclaim_bars + 1)):
            if C[i] > lvl and np.isfinite(v20[i]) and v20[i] > 0 and V[i] / v20[i] >= min_relvol:
                r = i
                break
        if r is None:
            continue
        # 3. weekly trend sharply up, read on the last CLOSED weekly bar
        wk = int(np.searchsorted(wlast, r, side="right")) - 1
        if wk < 0 or wk >= len(w_slope) or not np.isfinite(w_slope[wk]):
            continue
        if w_slope[wk] <= weekly_slope_min:
            continue
        # 4. the retest: price comes back to the 10 or 20 EMA
        t = None
        for i in range(r + 1, min(n, r + max_retest_bars + 1)):
            if L[i] <= ema_arr[i] and C[i] > lvl:          # touched the EMA, still above the low
                t = i
                break
        if t is None or t + 5 >= n or not np.isfinite(A[t]) or A[t] <= 0:
            continue
        out.append({
            "bar": t, "date": df.index[t], "entry_plan": float(C[t]),
            "atr_at_entry": float(A[t]),
            "swing_low": float(lvl), "sweep_bar": s, "reclaim_bar": r,
            "sweep_depth_atr": float((lvl - L[s]) / A[s]),
            "reclaim_bars": int(r - s), "reclaim_relvol": float(V[r] / v20[r]),
            "retest_bars": int(t - r), "retest_relvol": float(V[t] / v20[t]) if v20[t] > 0 else np.nan,
            "weekly_slope_pct": float(w_slope[wk]),
            "atr_pct": float(100 * A[t] / C[t]),
            "dist_ema20_atr": float((C[t] - e20[t]) / A[t]),
            "dist_ema50_atr": float((C[t] - e50[t]) / A[t]),
            "dist_ema200_atr": float((C[t] - e200[t]) / A[t]),
            "rsi14": float(rsi[t]),
            "above_swing_pct": float(100 * (C[t] / lvl - 1)),
            "turnover_cr": float(C[t] * v20[t] / 1e7) if np.isfinite(v20[t]) else np.nan,
        })
    return out
