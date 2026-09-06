"""GTF demand/supply research engine.

Standalone on purpose. The two-year audit (research/strategy_config.proposed.json)
found look-ahead in the production engine's higher-timeframe features, and the
brief's absolute rule is "never optimize a broken or contaminated backtest", so
nothing here imports from backend.app.engine.

Every function is point-in-time: a value computed for bar t uses bars <= t only.
The regression tests in test_gtfcore.py assert that property by truncation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- candles

BASE_BODY_RATIO = 0.50   # A1: exciting if body > 50% of range


def classify(o, h, l, c, body_ratio=BASE_BODY_RATIO):
    """A1 - exciting vs base. Returns (is_exciting, is_green).

    A zero-range bar has no body either, so it is a base candle.
    """
    rng = h - l
    body = np.abs(c - o)
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.where(rng > 0, body / np.where(rng > 0, rng, 1.0), 0.0)
    return frac > body_ratio, c >= o


# ---------------------------------------------------------------- resampling

def to_period(dates: pd.DatetimeIndex, freq: str) -> np.ndarray:
    """Period label per daily bar. 'W' = week (Mon-Sun), 'M' = calendar month."""
    if freq == "W":
        return (dates - pd.to_timedelta(dates.dayofweek, unit="D")).values
    if freq == "M":
        return dates.to_period("M").astype(str).values
    raise ValueError(freq)


def aggregate(df: pd.DataFrame, freq: str):
    """Aggregate daily OHLCV into higher-timeframe bars.

    Returns (bars, last_daily_index) where bars is a DataFrame of completed
    higher-timeframe candles and last_daily_index[k] is the index of the last
    daily bar belonging to higher-timeframe bar k. A caller evaluating daily
    bar t may use higher-timeframe bars k where last_daily_index[k] <= t, which
    is exactly the set of bars whose period had already closed.
    """
    per = to_period(df.index, freq)
    codes, _ = pd.factorize(per)
    n = codes[-1] + 1
    o = np.empty(n); h = np.empty(n); l = np.empty(n); c = np.empty(n)
    v = np.empty(n); last = np.empty(n, dtype=np.int64); first = np.empty(n, dtype=np.int64)
    O = df["open"].to_numpy(); H = df["high"].to_numpy()
    L = df["low"].to_numpy(); C = df["close"].to_numpy(); V = df["volume"].to_numpy()
    start = 0
    for k in range(n):
        end = start
        while end + 1 < len(codes) and codes[end + 1] == k:
            end += 1
        o[k] = O[start]; h[k] = H[start:end + 1].max()
        l[k] = L[start:end + 1].min(); c[k] = C[end]
        v[k] = V[start:end + 1].sum()
        first[k] = start; last[k] = end
        start = end + 1
    bars = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v})
    return bars, first, last


# ---------------------------------------------------------------- zones

class Zone:
    __slots__ = ("kind", "base_lo", "base_hi", "legout_start", "legout_n",
                 "n_base", "proximal", "distal", "gap", "closing_ok",
                 "legin_idx", "achievement", "formed_at", "legout_atr")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    @property
    def height(self):
        return abs(self.proximal - self.distal)

    def score(self, n_tests):
        """A12 - GTF trade score, max 7."""
        if n_tests == 0:
            fresh = 3.0
        elif n_tests == 1:
            fresh = 1.5
        else:
            fresh = 0.0
        strength = 2.0 if (self.legout_n >= 2 or self.gap) else 1.0
        if self.n_base <= 3:
            timeb = 2.0
        elif self.n_base <= 5:
            timeb = 1.0
        else:
            timeb = 0.0
        return fresh + strength + timeb


def find_zones(o, h, l, c, atr=None, max_base=12, kind="demand"):
    """A2/A3/A5/A6 - detect every demand (or supply) zone in a frame.

    A zone is leg-in (exciting) -> 1..max_base base candles -> leg-out
    (exciting, correct colour). Zones are returned in formation order; a zone
    formed at bar k used only bars <= k.
    """
    n = len(c)
    exciting, green = classify(o, h, l, c)
    want_green = kind == "demand"
    zones = []
    i = 1
    while i < n:
        if exciting[i]:
            i += 1
            continue
        # run of base candles starting at i
        j = i
        while j + 1 < n and not exciting[j + 1]:
            j += 1
        legin = i - 1
        legout = j + 1
        nb = j - i + 1
        if (legout < n and exciting[legin] and exciting[legout]
                and green[legout] == want_green and nb <= max_base):
            # count consecutive same-direction exciting leg-out candles
            k = legout
            cnt = 0
            while k < n and exciting[k] and green[k] == want_green:
                cnt += 1
                k += 1
            bl = l[i:j + 1].min()
            bh = h[i:j + 1].max()
            body_hi = np.maximum(o[i:j + 1], c[i:j + 1]).max()
            body_lo = np.minimum(o[i:j + 1], c[i:j + 1]).min()
            if want_green:
                prox, dist = body_hi, bl
                gap = o[legout] > bh
                # A6 closing: leg-out run closes above the leg-in high
                closing_ok = bool(c[legout:legout + cnt].max() > h[legin])
                # A5 achievement: how far past proximal the leg-out travelled
                ach = h[legout:legout + cnt].max() - prox
            else:
                prox, dist = body_lo, bh
                gap = o[legout] < bl
                closing_ok = bool(c[legout:legout + cnt].min() < l[legin])
                ach = prox - l[legout:legout + cnt].min()
            a = atr[legout] if atr is not None and np.isfinite(atr[legout]) else np.nan
            zones.append(Zone(
                kind=kind, base_lo=i, base_hi=j, legout_start=legout,
                legout_n=cnt, n_base=nb, proximal=float(prox), distal=float(dist),
                gap=bool(gap), closing_ok=closing_ok, legin_idx=legin,
                achievement=float(ach), formed_at=legout,
                legout_atr=float(ach / a) if a and np.isfinite(a) and a > 0 else np.nan,
            ))
            i = j + 1
        else:
            i = j + 1
    return zones


def zone_tests(zone, h, l, c, upto):
    """A4 - completed tests of a zone between its leg-out and bar `upto`.

    An excursion opens when price trades into the zone (touches the proximal
    line) and completes when price closes back outside it - the video's
    "टच करके ऊपर चली गई". Both can happen on the same bar.

    An excursion still open at `upto` is not a test, which is the distinction
    the video is explicit about: price sitting in the zone right now is the
    entry we are waiting for, not a spent zone.
    """
    start = zone.legout_start + zone.legout_n
    tests = 0
    inside = False
    prox = zone.proximal
    demand = zone.kind == "demand"
    for j in range(start, min(upto + 1, len(c))):
        if not inside:
            if (l[j] <= prox) if demand else (h[j] >= prox):
                inside = True
        if inside:
            if (c[j] > prox) if demand else (c[j] < prox):
                inside = False
                tests += 1
    return tests, inside


# ---------------------------------------------------------------- indicators

def sma(x, n):
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False, min_periods=n).mean().to_numpy()


def atr(h, l, c, n=14):
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy()


def rsi(x, n=14):
    d = np.diff(x, prepend=x[0])
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    # an all-up window has no average loss; RSI is 100 there, not undefined
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0).where(up != 0, out.fillna(50.0)).to_numpy()


def trend_slope(x, lookback=6):
    """A7 - the clock rule: SMA50 now vs SMA50 seven candles back (t-6)."""
    prev = np.roll(x, lookback)
    prev[:lookback] = np.nan
    return x - prev


def trend_state(x, lookback=6, flat_eps=0.0):
    d = trend_slope(x, lookback)
    with np.errstate(invalid="ignore"):
        rel = np.where(np.isfinite(x) & (x != 0), d / np.abs(x), np.nan)
    st = np.full(len(x), 0, dtype=np.int8)
    st[rel > flat_eps] = 1
    st[rel < -flat_eps] = -1
    st[~np.isfinite(rel)] = 0
    return st
