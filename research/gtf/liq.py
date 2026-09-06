"""Liquidity grabs, sweeps and runs, as the transcript defines them.

My first attempt (sweep.py) failed out of sample. Reading the course showed
the implementation was not the speaker's setup at all, in four ways:

  1. LEVELS. I used k=5 pivots. Those are what the speaker calls INTERNAL
     liquidity - "minor swing points". He says to trade EXTERNAL liquidity,
     "simply the most obvious levels, the most clear levels you can" find,
     and that internal liquidity gets taken first precisely because it is
     the easy one. So levels here are wide pivots, and EQUAL LOWS stacked
     at one price ("multiple swing points that stack on the same price
     often create a deeper liquidity pool") count as one deeper level.

  2. THREE PATTERNS, NOT ONE. Taking a level is not automatically a
     reversal. The speaker separates:
       grab  - "a fast and strong wick that pokes through a level and then
                immediately reacts"
       sweep - "a slow liquidity grab": closes through, then reverses over
               several candles, with a confirmation candle
       run   - "the price takes the level but keeps going ... more similar
               to a real breakout"
     Grab and sweep are reversal trades; the run is a breakout trade in the
     SAME direction as the break. I previously treated every break of a low
     as a long, which mixes a reversal setup with its own failure case.

  3. THE DISCRIMINATORS ARE EXPLICIT. A run closes far beyond the level,
     has a small wick, and comes with heavy volume on the breakout candle.
     A sweep closes beyond but leaves a big wick. And the momentum rule is
     numeric: "I want the real body of the momentum candles to be at least
     twice the size of the previous candle."

  4. THE ENTRY IS THE CONFIRMATION CANDLE, not an EMA retest. The EMA
     retest was mine, not his.

Targets come from the course too: high-resistance liquidity forms after a
clean break (a low, then a lower low, then a reversal to a higher high),
low-resistance liquidity after a failure swing, and "once high resistance
liquidity is taken the price tends to travel toward the low resistance
liquidity". So the target is the nearest untapped opposing pool.

Every value at bar i uses bars <= i only. A pivot at p is not knowable
until p+k and is never used before then. There is deliberately no
"needs N more bars" guard here: a setup must be findable on the day it
forms, exactly as a live scan would find it. Dropping rows with too little
forward path to score is the caller's job.
"""
from __future__ import annotations
import numpy as np, pandas as pd
import gtfcore as G

COST = 0.23


# ---------------------------------------------------------------- levels

def pivots(L, H, k):
    """(index, bar it becomes knowable) for pivot lows and pivot highs."""
    n = len(L)
    lo, hi = [], []
    for p in range(k, n - k):
        w = L[p - k:p + k + 1]
        if (w[:k] > L[p]).all() and (w[k + 1:] > L[p]).all():
            lo.append(p)
        w = H[p - k:p + k + 1]
        if (w[:k] < H[p]).all() and (w[k + 1:] < H[p]).all():
            hi.append(p)
    return [(p, p + k) for p in lo], [(p, p + k) for p in hi]


def build_pools(L, H, k, tol_frac):
    """One level per pivot, carrying only what was knowable when it confirmed.

    Equal lows are the point - "multiple swing points that stack on the same
    price often create a deeper liquidity pool" - but a pool must not be
    deepened, repriced or delayed by a touch that has not happened yet. So
    each pivot yields its own level, and its touches count is the number of
    ALREADY-CONFIRMED pivots sitting at the same price. A cluster therefore
    appears as a sequence of progressively deeper levels, which is exactly
    what a trader watching it form would see.
    """
    plo, phi = pivots(L, H, k)
    lows, highs = [], []
    for piv, px, side, dest in ((plo, L, "low", lows), (phi, H, "high", highs)):
        for p, known in piv:
            mem = [q for q, kq in piv if kq <= known
                   and abs(px[q] / px[p] - 1) <= tol_frac]
            lvl = min(float(px[q]) for q in mem) if side == "low" \
                else max(float(px[q]) for q in mem)
            dest.append({"px": lvl, "first": p, "known": known,
                         "touches": len(mem), "side": side})
    return lows, highs


def resistance_class(pool, prior_lows, prior_highs, L, H):
    """low- or high-resistance, per the failure-swing / clean-break rule.

    For sellside liquidity under a low: if the low is HIGHER than the
    previous swing low, price tried to make a new low and failed - a
    failure swing - so the pool is low resistance and weaker. If it is a
    LOWER low that then reversed to a higher high, it is a clean break and
    the pool is high resistance and stronger.
    """
    p = pool["first"]
    same = prior_lows if pool["side"] == "low" else prior_highs
    prev = [q for q in same if q < p]
    if not prev:
        return "unknown"
    q = max(prev)
    if pool["side"] == "low":
        return "low_res" if L[p] > L[q] else "high_res"   # failure swing vs lower low
    return "low_res" if H[p] < H[q] else "high_res"


# ------------------------------------------------------------- patterns

def _bodies(O, C):
    return np.abs(C - O)


def find_setups(df, k=10, eq_tol=0.010, momentum=2.0, sweep_max_bars=5,
                run_close_atr=0.5, run_wick_frac=0.30, run_vol=1.5,
                grab_wick_frac=0.40, level_max_age=250, want=("grab", "sweep", "run")):
    """One row per completed setup. Entry is the close of the confirming candle."""
    O = df["open"].to_numpy(); H = df["high"].to_numpy()
    L = df["low"].to_numpy(); C = df["close"].to_numpy(); V = df["volume"].to_numpy()
    n = len(C)
    if n < 320:
        return []
    A = G.atr(H, L, C, 14)
    B = _bodies(O, C)
    RNG = H - L
    e10 = G.ema(C, 10); e20 = G.ema(C, 20); e50 = G.ema(C, 50); e200 = G.ema(C, 200)
    v20 = pd.Series(V).rolling(20, min_periods=20).mean().to_numpy()
    rsi = G.rsi(C, 14)

    wb, _, wlast = G.aggregate(df, "W")
    wc = wb["close"].to_numpy()
    w_sma = G.sma(wc, 20)
    w_slope = np.full(len(wc), np.nan)
    w_slope[6:] = (w_sma[6:] / w_sma[:-6] - 1) * 100

    lows, highs = build_pools(L, H, k, eq_tol)
    lo_idx = [pl["first"] for pl in lows]
    hi_idx = [ph["first"] for ph in highs]
    for pool in lows + highs:
        pool["res"] = resistance_class(pool, lo_idx, hi_idx, L, H)

    def wk_slope(i):
        j = int(np.searchsorted(wlast, i, side="right")) - 1
        if j < 0 or j >= len(w_slope) or not np.isfinite(w_slope[j]):
            return np.nan
        return float(w_slope[j])

    def opposing(px_side, i, ref):
        """Nearest untapped pool on the other side, and its resistance class."""
        best, cls, tch = np.nan, "none", 0
        pools = highs if px_side == "high" else lows
        for pool in pools:
            if pool["known"] >= i:
                continue
            if px_side == "high":
                if pool["px"] <= ref:
                    continue
                # untapped: not traded through since it was confirmed
                if H[pool["known"]:i + 1].max() >= pool["px"]:
                    continue
                if not np.isfinite(best) or pool["px"] < best:
                    best, cls, tch = pool["px"], pool["res"], pool["touches"]
            else:
                if pool["px"] >= ref:
                    continue
                if L[pool["known"]:i + 1].min() <= pool["px"]:
                    continue
                if not np.isfinite(best) or pool["px"] > best:
                    best, cls, tch = pool["px"], pool["res"], pool["touches"]
        return best, cls, tch

    def row(kind, side, pool, take, conf, extreme):
        i = conf
        if not np.isfinite(A[i]) or A[i] <= 0:
            return None
        if not np.isfinite(v20[i]) or v20[i] <= 0:
            return None
        tgt, tcls, ttch = opposing("high" if side == "long" else "low", i,
                                   C[i])
        return {"kind": kind, "side": side, "bar": i, "date": df.index[i],
                "entry_plan": float(C[i]), "atr_at_entry": float(A[i]),
                "level": pool["px"], "level_touches": pool["touches"],
                "level_res": pool["res"],
                "level_age": int(i - pool["first"]),
                "take_bar": int(take), "conf_bars": int(conf - take),
                "extreme": float(extreme),
                "stop_struct": float(extreme),
                "poke_atr": float(abs(pool["px"] - extreme) / A[i]),
                "take_relvol": float(V[take] / v20[take]) if v20[take] > 0 else np.nan,
                "conf_relvol": float(V[i] / v20[i]),
                "conf_body_mult": float(B[i] / B[i - 1]) if B[i - 1] > 0 else np.inf,
                "target_liq": float(tgt), "target_res": tcls,
                "target_touches": int(ttch),
                "target_atr": float(abs(tgt - C[i]) / A[i]) if np.isfinite(tgt) else np.nan,
                "weekly_slope_pct": wk_slope(i),
                "atr_pct": float(100 * A[i] / C[i]),
                "dist_ema20_atr": float((C[i] - e20[i]) / A[i]),
                "dist_ema50_atr": float((C[i] - e50[i]) / A[i]),
                "dist_ema200_atr": float((C[i] - e200[i]) / A[i]),
                "rsi14": float(rsi[i]),
                "turnover_cr": float(C[i] * v20[i] / 1e7)}

    out = []
    for pool in lows:                      # sellside liquidity -> long reversals
        lvl = pool["px"]; start = pool["known"] + 1
        take = None
        for i in range(start, min(n, start + level_max_age)):
            if L[i] < lvl:
                take = i; break
            if C[i] > lvl * 1.5:
                break
        if take is None or not np.isfinite(A[take]) or A[take] <= 0:
            continue
        i = take
        lw = min(O[i], C[i]) - L[i]
        run = (C[i] < lvl and (lvl - C[i]) / A[i] >= run_close_atr
               and RNG[i] > 0 and lw <= run_wick_frac * RNG[i]
               and np.isfinite(v20[i]) and v20[i] > 0 and V[i] >= run_vol * v20[i]
               and B[i - 1] > 0 and B[i] >= momentum * B[i - 1])
        if run:
            if "run" in want:
                r = row("run", "short", pool, take, i, float(L[i]))
                if r: out.append(r)
            continue
        if C[i] > lvl and RNG[i] > 0 and lw >= grab_wick_frac * RNG[i]:
            if "grab" in want:              # poked through and immediately reacted
                r = row("grab", "long", pool, take, i, float(L[i]))
                if r: out.append(r)
            continue
        if "sweep" not in want:
            continue
        ext = L[i]                          # slow: wait for the confirmation candle
        conf = None
        for j in range(i + 1, min(n, i + sweep_max_bars + 1)):
            ext = min(ext, L[j])
            if C[j] > lvl and C[j] > O[j] and B[j - 1] > 0 and B[j] >= momentum * B[j - 1]:
                conf = j; break
        if conf is not None:
            r = row("sweep", "long", pool, take, conf, float(ext))
            if r: out.append(r)

    for pool in highs:                     # buyside liquidity -> long breakouts
        lvl = pool["px"]; start = pool["known"] + 1
        take = None
        for i in range(start, min(n, start + level_max_age)):
            if H[i] > lvl:
                take = i; break
            if C[i] < lvl * 0.5:
                break
        if take is None or not np.isfinite(A[take]) or A[take] <= 0:
            continue
        i = take
        uw = H[i] - max(O[i], C[i])
        run = (C[i] > lvl and (C[i] - lvl) / A[i] >= run_close_atr
               and RNG[i] > 0 and uw <= run_wick_frac * RNG[i]
               and np.isfinite(v20[i]) and v20[i] > 0 and V[i] >= run_vol * v20[i]
               and B[i - 1] > 0 and B[i] >= momentum * B[i - 1])
        if run:
            if "run" in want:
                r = row("run", "long", pool, take, i, float(L[i]))
                if r: out.append(r)
            continue
        if C[i] < lvl and RNG[i] > 0 and uw >= grab_wick_frac * RNG[i]:
            if "grab" in want:
                r = row("grab", "short", pool, take, i, float(H[i]))
                if r: out.append(r)
            continue
        if "sweep" not in want:
            continue
        ext = H[i]
        conf = None
        for j in range(i + 1, min(n, i + sweep_max_bars + 1)):
            ext = max(ext, H[j])
            if C[j] < lvl and C[j] < O[j] and B[j - 1] > 0 and B[j] >= momentum * B[j - 1]:
                conf = j; break
        if conf is not None:
            r = row("sweep", "short", pool, take, conf, float(ext))
            if r: out.append(r)

    # A cluster of equal lows yields one level per touch, and each of those
    # finds the same break. Keep the deepest (most touches) reading of it.
    best = {}
    for r in out:
        key = (r["take_bar"], r["side"], r["kind"])
        if key not in best or r["level_touches"] > best[key]["level_touches"]:
            best[key] = r
    return sorted(best.values(), key=lambda r: r["bar"])


# ----------------------------------------------------------------- exits

def walk(O, H, L, C, j, entry, stop, target, hold=60, long=True):
    """Bar 0 can stop us out; it cannot pay us. Same rule as everywhere else."""
    n = len(C); end = min(j + hold, n - 1)
    sgn = 1.0 if long else -1.0
    for m in range(j, end + 1):
        if long:
            if L[m] <= stop:
                px = min(stop, O[m]) if m > j else stop
                return 100.0 * (px / entry - 1) - COST, m - j, "stop"
            if m > j and target and H[m] >= target:
                return 100.0 * (target / entry - 1) - COST, m - j, "target"
        else:
            if H[m] >= stop:
                px = max(stop, O[m]) if m > j else stop
                return -100.0 * (px / entry - 1) - COST, m - j, "stop"
            if m > j and target and L[m] <= target:
                return -100.0 * (target / entry - 1) - COST, m - j, "target"
    return sgn * 100.0 * (C[end] / entry - 1) - COST, end - j, "time"
