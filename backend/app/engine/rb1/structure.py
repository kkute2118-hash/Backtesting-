"""Swings, trend state and order blocks. A pivot at bar k is known only once
bar k + SWING_PIVOT_BARS has closed."""

from __future__ import annotations

import numpy as np

from . import config as C

UNCLEAR, UP, DOWN, RANGE = 0, 1, 2, 3
TREND_NAMES = {UNCLEAR: "UNCLEAR", UP: "UP", DOWN: "DOWN", RANGE: "RANGE"}


def pivots(h: np.ndarray, l: np.ndarray, n: int = C.SWING_PIVOT_BARS):
    """Boolean arrays: bar k is a swing high / low (strictly beyond n bars each side)."""
    m = len(h)
    sh = np.zeros(m, bool)
    sl = np.zeros(m, bool)
    for k in range(n, m - n):
        win_h = np.r_[h[k - n:k], h[k + 1:k + n + 1]]
        win_l = np.r_[l[k - n:k], l[k + 1:k + n + 1]]
        sh[k] = h[k] > win_h.max()
        sl[k] = l[k] < win_l.min()
    return sh, sl


def trend_states(h, l, c, n: int = C.SWING_PIVOT_BARS):
    """Per bar (as of its close): trend state and the last confirmed swing high / low.

    State from the last two confirmed swing highs and lows: HH+HL = UP,
    LH+LL = DOWN, otherwise RANGE; fewer than two of each = UNCLEAR. A close
    beyond the last confirmed swing high (low) flips the state to UP (DOWN)
    until the next swing is confirmed.
    """
    sh, sl = pivots(h, l, n)
    m = len(h)
    state = np.zeros(m, np.int8)
    last_sh = np.full(m, np.nan)
    last_sl = np.full(m, np.nan)
    highs, lows = [], []
    cur = UNCLEAR
    for j in range(m):
        k = j - n                              # the pivot this bar confirms
        new = False
        if k >= n:
            if sh[k]:
                highs.append(h[k]); new = True
            if sl[k]:
                lows.append(l[k]); new = True
        if new:
            if len(highs) >= 2 and len(lows) >= 2:
                hh, hl = highs[-1] > highs[-2], lows[-1] > lows[-2]
                cur = UP if hh and hl else DOWN if not hh and not hl else RANGE
            else:
                cur = UNCLEAR
        if highs and c[j] > highs[-1] and cur != UNCLEAR:
            cur = UP
        elif lows and c[j] < lows[-1] and cur != UNCLEAR:
            cur = DOWN
        state[j] = cur
        last_sh[j] = highs[-1] if highs else np.nan
        last_sl[j] = lows[-1] if lows else np.nan
    return state, last_sh, last_sl


def order_blocks(o, h, l, c, t_close, n: int = C.SWING_PIVOT_BARS):
    """Order blocks: when a close breaks the last confirmed swing high (low),
    the last opposite-coloured candle at the bottom (top) of the impulse leg.
    Returns (created_time, lo, hi, side) with side +1 bullish (support), -1 bearish."""
    sh, sl = pivots(h, l, n)
    out = []
    last_hi = last_lo = None                   # (index, price, broken)
    for j in range(len(h)):
        k = j - n
        if k >= n:
            if sh[k]:
                last_hi = [k, h[k], False]
            if sl[k]:
                last_lo = [k, l[k], False]
        if last_hi and not last_hi[2] and c[j] > last_hi[1]:
            last_hi[2] = True
            seg = slice(last_hi[0] + 1, j + 1)
            if seg.start < j + 1:
                b = seg.start + int(np.argmin(l[seg]))
                for q in range(b, max(b - 3, -1), -1):
                    if c[q] < o[q]:
                        out.append((t_close[j], l[q], h[q], 1)); break
        if last_lo and not last_lo[2] and c[j] < last_lo[1]:
            last_lo[2] = True
            seg = slice(last_lo[0] + 1, j + 1)
            if seg.start < j + 1:
                b = seg.start + int(np.argmax(h[seg]))
                for q in range(b, max(b - 3, -1), -1):
                    if c[q] > o[q]:
                        out.append((t_close[j], l[q], h[q], -1)); break
    return out
