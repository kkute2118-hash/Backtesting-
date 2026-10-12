"""Order-flow delta from Binance taker-buy volume (crypto only).

delta = 2 * taker_buy_volume - volume. Gold and forex have no taker volume:
every function returns None for them, so the delta filter switches itself off
instead of being faked.
"""

from __future__ import annotations

import numpy as np

from . import candles as K
from . import config as C


def delta_sign(volume: float, taker_buy: float) -> int | None:
    """+1 buying, -1 selling, 0 neutral; None when there is no taker volume."""
    if taker_buy is None or not np.isfinite(taker_buy) or not np.isfinite(volume) or volume <= 0:
        return None
    d = 2 * taker_buy - volume
    if abs(d) / volume < C.DELTA_NEUTRAL_PCT:
        return 0
    return 1 if d > 0 else -1


def absorption(i: int, o, h, l, c, v, tb, cls, at_resistance: bool, at_support: bool) -> int | None:
    """Absorption confirmed at bar i (both bars closed), else 0; None without taker volume.

    Bearish (-1): bar i-1 at resistance is red or an HPR with buying delta, and
    bar i breaks its low with a red body and selling delta. Bullish (+1): mirror.
    """
    if i < 1:
        return 0
    s_prev, s_now = delta_sign(v[i - 1], tb[i - 1]), delta_sign(v[i], tb[i])
    if s_prev is None or s_now is None:
        return None
    if (at_resistance and (c[i - 1] < o[i - 1] or cls[i - 1] == K.HPR) and s_prev > 0
            and l[i] < l[i - 1] and c[i] < o[i] and s_now < 0):
        return -1
    if (at_support and (c[i - 1] > o[i - 1] or cls[i - 1] == K.LPR) and s_prev < 0
            and h[i] > h[i - 1] and c[i] > o[i] and s_now > 0):
        return 1
    return 0
