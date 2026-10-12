"""Candle classifier (SOURCE_STATED classes; thresholds NEEDS_TUNING, config.py)."""

from __future__ import annotations

import numpy as np

from . import config as C

NONE, BULL_POWER, BEAR_POWER, LPR, HPR = 0, 1, 2, 3, 4
NAMES = {NONE: "NONE", BULL_POWER: "BULL_POWER", BEAR_POWER: "BEAR_POWER", LPR: "LPR", HPR: "HPR"}


def classify(o: float, h: float, l: float, c: float, atr: float) -> int:
    """One bar. LPR/HPR (long lower / upper wick) ignore body colour; when a
    bar meets a rejection rule it is a rejection, else a power candle if it
    meets that rule."""
    rng = h - l
    if rng <= 0 or not np.isfinite(atr):
        return NONE
    body = abs(c - o)
    lower = min(o, c) - l
    upper = h - max(o, c)
    if lower >= C.REJ_WICK_TO_BODY * body and lower >= C.REJ_WICK_PCT * rng and lower > upper:
        return LPR
    if upper >= C.REJ_WICK_TO_BODY * body and upper >= C.REJ_WICK_PCT * rng and upper > lower:
        return HPR
    if body >= C.POWER_BODY_PCT * rng and rng >= C.POWER_MIN_RANGE_ATR * atr:
        if c > o and (c - l) >= (1 - C.POWER_CLOSE_ZONE) * rng:
            return BULL_POWER
        if c < o and (h - c) >= (1 - C.POWER_CLOSE_ZONE) * rng:
            return BEAR_POWER
    return NONE


def classify_all(o, h, l, c, atr) -> np.ndarray:
    return np.array([classify(*v) for v in zip(o, h, l, c, atr)], dtype=np.int8)
