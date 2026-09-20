"""Deterministic features from the trader methodology.

Only the calculations the transcripts state exactly. Everything the author leaves as a
judgement call - candle quality, expansion quality, "relativity" - is deliberately
absent, because approximating it here would let an approximation pass for his rule.
Those belong in the research layer, labelled as approximations, and have to be
validated against his own worked examples before anyone trusts them.

Nothing here touches the scanners. This module reads OHLCV and returns numbers.

Reference: research/trader_methodology/
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# The author's own period, stated twice in lecture 12 ("average turnover last 20
# days"). Our platform's 21-day turnover window is a separate setting and stays
# separate - collapsing them would quietly rewrite his rule into ours.
AUTHOR_AVERAGE_TURNOVER_LOOKBACK = 20

EMA_PERIODS = (10, 20, 50, 200)


def emas(close: pd.Series, periods=EMA_PERIODS) -> pd.DataFrame:
    return pd.DataFrame(
        {f"ema{p}": close.ewm(span=p, adjust=False).mean() for p in periods}
    )


def turnover_cr(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Daily turnover in rupees crore - the unit the author quotes throughout."""
    return close * volume / 1e7


def avg_turnover(
    close: pd.Series,
    volume: pd.Series,
    lookback: int = AUTHOR_AVERAGE_TURNOVER_LOOKBACK,
) -> pd.Series:
    return turnover_cr(close, volume).rolling(lookback, min_periods=lookback).mean()


def turnover_spike_ratio(close: pd.Series, volume: pd.Series, **kw) -> pd.Series:
    """Today against the 20-day average.

    The author's examples run 5-7x on the days he calls "big" (175 cr average against
    a 1,250 cr day). He never states a threshold, so none is applied here.
    """
    return turnover_cr(close, volume) / avg_turnover(close, volume, **kw)


def avg_turnover_slope(close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    """Slope of the 20-day average turnover, normalised by its own level.

    He tracks the average itself climbing through a move - 175 to 200 to 255 - and
    treats that as confirmation that money arrived and stayed. A one-day spike that
    leaves the average flat is the turnover analogue of a single tower of volume.
    """
    avg = avg_turnover(close, volume)
    return (avg - avg.shift(window)) / avg.shift(window)


def ema_separation(close: pd.Series) -> pd.Series:
    """|EMA10 - EMA20| / close.

    Lecture 5: "make sure 10 has a clearly visible distance between 20 moving
    average". Lecture 9 names the failure mode - "it's 10 EMA currently intermingled
    with the 20". What counts as clearly visible is not stated, so the caller picks the
    floor and owns it.
    """
    e = emas(close, (10, 20))
    return (e["ema10"] - e["ema20"]).abs() / close


def ema_compression(close: pd.Series) -> pd.Series:
    """Spread of all four EMAs, normalised by price.

    Lecture 7's strongest configuration: 10, 20, 50 and 200 at a single point, where
    the stock has no work left to do. Small values are the interesting ones.
    """
    e = emas(close)
    return (e.max(axis=1) - e.min(axis=1)) / close


def ema_stack_ok(close: pd.Series) -> pd.Series:
    """10 > 20 > 50."""
    e = emas(close, (10, 20, 50))
    return (e["ema10"] > e["ema20"]) & (e["ema20"] > e["ema50"])


def cross_above(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """The bar where fast crosses above slow.

    For the 10/20 pair this is the "small black dot" the author points at on his chart
    (lecture 11).
    """
    return (fast > slow) & (fast.shift(1) <= slow.shift(1))


def event_survived(close: pd.Series, hold_bars: int) -> pd.Series:
    """Has 10-above-20 held for every bar of the last `hold_bars`?

    Lecture 7 turns on this. Two areas of the same chart looked alike; in the first an
    up move crossed the averages and "all the hard work was undone by the horrible
    contraction", in the second the configuration held and the stock made its largest
    move ever. A cross that reverted is not an event.
    """
    e = emas(close, (10, 20))
    above = (e["ema10"] > e["ema20"]).astype(int)
    return above.rolling(hold_bars, min_periods=hold_bars).min() == 1


def up_move_pct(close: pd.Series, start: int, end: int) -> float:
    """Sum of positive daily returns across a leg.

    Lecture 11 rejects high-minus-low for this: "a lot of people ask, shall I do like
    this? I'll tell you a better way ... simply add on the positive candles. So it's
    not 175. 100% up move we had." Getting this wrong inflates every DNA figure and so
    every target derived from one.
    """
    r = close.iloc[start : end + 1].pct_change().dropna()
    return float(r[r > 0].sum() * 100)


def expansion_end_bar(close: pd.Series, lookback: int) -> int:
    """Causal marker for where the expansion stopped.

    The author picks "the candle with which the expansion ended" by eye and in
    hindsight. Highest close in the window, fixed as of the decision bar and never
    revised, is the honest causal stand-in. Different definition, same role - and the
    look-ahead check in backtest_spec.md exists to catch it if it drifts.
    """
    window = close.iloc[-lookback:]
    return int(window.values.argmax()) + len(close) - lookback


def containment_ok(high: pd.Series, end_bar: int) -> bool:
    """Has the contraction stayed inside the high of the expansion-ending candle?

    Lecture 4: "this entire contraction you see happening was within where the
    contraction started - really important ... this is one of the most important points
    that I'll ever give you in your trading."
    """
    if end_bar >= len(high) - 1:
        return True
    return bool(high.iloc[end_bar + 1 :].max() <= high.iloc[end_bar])


def upper_half_ok(high: pd.Series, low: pd.Series, end_bar: int) -> bool:
    """Is the contraction in the upper half of that candle's range?

    Same passage: "everything was in the upper half of the contraction - that adds to
    the deep versus shallow [question]".
    """
    if end_bar >= len(low) - 1:
        return True
    mid = (high.iloc[end_bar] + low.iloc[end_bar]) / 2
    return bool(low.iloc[end_bar + 1 :].min() >= mid)


def body(open_: pd.Series, close: pd.Series) -> pd.Series:
    return (close - open_).abs()


def counter_ratio(open_: pd.Series, close: pd.Series, red_bar: int, up_bar: int) -> float:
    """Up-candle body against the red candle it is supposed to answer.

    The author wants >= 0.5 and prefers a full engulf. Below that, lecture 12: "these
    two candles are hovering below the 50% of this candle ... the immediate left-hand
    side is showing you selling pressure."
    """
    red = abs(close.iloc[red_bar] - open_.iloc[red_bar])
    up = abs(close.iloc[up_bar] - open_.iloc[up_bar])
    return float(up / red) if red else np.inf


def engulfs_prior_expansion(
    open_: pd.Series, close: pd.Series, high: pd.Series, low: pd.Series, i: int
) -> bool:
    """The lecture 8 sell signal.

    "This is the first candle which completely eats the entire expansion candle, and in
    fact it is much bigger than the recent expansion candles ... You will never see the
    good stocks do this. Never." He exits on the break of its low, not at its close.
    """
    if i < 1:
        return False
    down = close.iloc[i] < open_.iloc[i]
    eats = (high.iloc[i] >= high.iloc[i - 1]) and (low.iloc[i] <= low.iloc[i - 1])
    bigger = body(open_, close).iloc[i] > body(open_, close).iloc[i - 1]
    return bool(down and eats and bigger)


def risk_distance(entry: float, pivot_low: float, buffer: float = 0.0) -> float:
    """Entry to structural stop, as a fraction of entry.

    The whole selection argument runs through this number. Lecture 10: "your position
    size is directly controlled by the kind of SL you are taking" - so a setup with no
    definable pivot is not merely riskier, it is unsizeable, and he skips it.
    """
    stop = pivot_low * (1 - buffer)
    return float((entry - stop) / entry)


def ma_proximity(open_: float, close: float, ma: float) -> tuple[float, float]:
    """How near the MA the candle opened and closed, as fractions of the MA.

    Lecture 5's four scenarios. Case 2 - both small - is the one he wants: the open
    near the MA puts the pivot close by so the stop is tight, and the close near the MA
    leaves no room for volatility, which is what lets a VCC form at all.
    """
    return abs(open_ - ma) / ma, abs(close - ma) / ma
