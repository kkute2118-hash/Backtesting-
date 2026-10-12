"""Levels and confluence (rulebook scores in config.LEVEL_SCORES).

Kinds: PDH/PDL (previous day's wick high/low), VAH/VAL (previous day's 70%
value area; never the POC), HTF_OB (15m and 1H order blocks, unmitigated),
TRIPLE_TOUCH (three or more turning points within ZONE_MERGE_ATR; zone from
body to wick), CDH/CDL (current day's high/low, only once the day's range is
at least CDH_CDL_ATR_GATE x daily ATR). Session highs/lows, previous
open/close and double tops are left out on purpose (SOURCE_STATED).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import config as C


@dataclass
class Level:
    kind: str          # PDH, PDL, VAH, VAL, HTF_OB, TRIPLE_TOUCH, CDH, CDL
    lo: float
    hi: float
    side: int          # -1 resistance (above price), +1 support (below), 0 either
    score: int
    touches: int = 0

    @property
    def group(self) -> str:
        return {"PDH": "PDH_PDL", "PDL": "PDH_PDL", "VAH": "VAH_VAL", "VAL": "VAH_VAL",
                "CDH": "CDH_CDL", "CDL": "CDH_CDL"}.get(self.kind, self.kind)


def value_area(prices: np.ndarray, volumes: np.ndarray, pct: float = C.VALUE_AREA_PCT,
               bins: int = C.VALUE_AREA_BINS) -> tuple[float, float] | None:
    """(VAL, VAH) of a volume profile: from the POC bin, add the larger
    neighbour until pct of the volume is covered."""
    ok = np.isfinite(prices) & np.isfinite(volumes) & (volumes > 0)
    if ok.sum() < 3:
        return None
    p, v = prices[ok], volumes[ok]
    lo, hi = p.min(), p.max()
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    hist, _ = np.histogram(p, bins=edges, weights=v)
    total = hist.sum()
    a = b = int(np.argmax(hist))
    acc = hist[a]
    while acc < pct * total and (a > 0 or b < bins - 1):
        left = hist[a - 1] if a > 0 else -1
        right = hist[b + 1] if b < bins - 1 else -1
        if right >= left:
            b += 1; acc += hist[b]
        else:
            a -= 1; acc += hist[a]
    return float(edges[a]), float(edges[b + 1])


def triple_zones(piv_idx, piv_price, piv_body, merge: float, side: int) -> list[Level]:
    """Clusters of turning points within `merge` of each other.
    side -1: pivot highs (resistance), zone from the lowest body top to the
    highest wick; side +1: pivot lows (support), mirror."""
    if len(piv_price) < C.MIN_ZONE_TOUCHES:
        return []
    order = np.argsort(piv_price)
    p, b = np.asarray(piv_price)[order], np.asarray(piv_body)[order]
    zones, start = [], 0
    for j in range(1, len(p) + 1):
        if j == len(p) or p[j] - p[j - 1] > merge:
            n = j - start
            if n >= C.MIN_ZONE_TOUCHES:
                if side < 0:
                    lo, hi = float(b[start:j].min()), float(p[start:j].max())
                else:
                    lo, hi = float(p[start:j].min()), float(b[start:j].max())
                zones.append(Level("TRIPLE_TOUCH", min(lo, hi), max(lo, hi), side,
                                   C.LEVEL_SCORES["TRIPLE_TOUCH"], n))
            start = j
    return zones


def distance(a: Level, b: Level) -> float:
    """Gap between two price intervals (0 when they overlap)."""
    return max(0.0, max(a.lo, b.lo) - min(a.hi, b.hi))


def confluence(level: Level, levels: list[Level], merge: float) -> int:
    """Sum of the scores of level groups within `merge` of `level` (each group counted once)."""
    best: dict[str, int] = {}
    for x in levels:
        if distance(level, x) <= merge:
            best[x.group] = max(best.get(x.group, 0), x.score)
    best[level.group] = max(best.get(level.group, 0), level.score)
    return sum(best.values())
