"""Entry timing from the two RichRoad case studies.

The scanners say WHICH stock. This says WHEN, and it is a different question.
His own workflow is scan, watchlist, wait, then enter - "Once I have selected
my STF and hypothesis of the trade, then only I will use ETF to plan my
entries. This is Important, always top down and never bottom up." Entering on
the scan bar is not his method; entering on the setup that follows it is.

Three setups, named in the PDFs:

  M10   price pulls back to the 10 EMA
  V12   price in the value zone between the 10 and 20 EMA
  V25   price in the value zone between the 20 and 50 EMA

M10 is stated outright ("We got a proper M10. Daily comes to 10 EMA"). V12 and
V25 are DERIVED: the PDFs use the labels without expanding them, but every
usage lines up with the 10/20 and 20/50 bands and with his "value zone"
language. Marked as derived wherever it matters.

WHAT IS MISSING, and it is the important part. His real entry is a three-scale
confluence - "Daily comes to 10 EMA. Hourly to 50 EMA. 15 min to 200 MA" - and
he enters on the last of those. That is where the 3% stop comes from; the same
trade taken on the daily is 6-10%. Our candle store holds daily bars only, so
everything here is his weekly-STF case at best. It should be judged against a
6% stop, not against the case studies' headline numbers.

Reference: research/trader_methodology/CASE_STUDIES_ADDENDUM.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PARAMS = {
    "MAX_WAIT_BARS": 15,      # how long a scan candidate stays on the watchlist
    "ZONE_TOL": 0.015,        # how near an EMA counts as "at" it
    "SWING_SPAN": 2,          # bars each side that define a swing low
    "BIG_CANDLE_PCT": 3.0,    # "a big candle on high volumes"
    "VOL_MULT": 1.3,          # what "high volumes" means against the 20-bar median
    "STOP_BUFFER": 0.005,
}


def emas(close: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({f"ema{n}": close.ewm(span=n, adjust=False).mean()
                         for n in (10, 20, 50)}, index=close.index)


def inside_bar(high: pd.Series, low: pd.Series, i: int) -> bool:
    """IB in the glossary's sense: this bar's range sits inside the last one."""
    if i < 1:
        return False
    return bool(high.iloc[i] <= high.iloc[i - 1] and low.iloc[i] >= low.iloc[i - 1])


def swing_lows(low: pd.Series, span: int | None = None) -> list[int]:
    """Bars that are the lowest of their neighbourhood - the structure points.

    These are what "HL" and "structure broke" are talking about, and what the
    stop goes under.
    """
    s = span or PARAMS["SWING_SPAN"]
    out = []
    v = low.to_numpy()
    for i in range(s, len(v) - s):
        if v[i] == v[i - s : i + s + 1].min() and v[i] < v[i - 1]:
            out.append(i)
    return out


def structure_intact(low: pd.Series, i: int, lookback: int = 60) -> bool:
    """Is the higher-low sequence still standing at bar i?

    This is the test the Kalyan study uses to explain a setup that did NOT
    work: "D did not give M10. Why? Structure broke by the time D came to 10
    EMA. Since HL was broken by the time D came to 10 EMA, price had difficulty
    moving up from there."

    So a pullback reaching the 10 EMA is not an M10 by itself. The structure
    has to have survived the trip.
    """
    lows = [j for j in swing_lows(low.iloc[max(0, i - lookback): i + 1])]
    if len(lows) < 2:
        return True                       # nothing to break yet
    base = max(0, i - lookback)
    a, b = base + lows[-2], base + lows[-1]
    return bool(low.iloc[b] > low.iloc[a])


def approach_mode(low: pd.Series, i: int, lookback: int = 60) -> str:
    """Is price arriving at the average on a higher low or a lower low?

    The Monthly entry in the Kalyan study turns entirely on this: "prior to
    that the candles were making Lower Lows(LLs) approaching the 10 EMA, only
    candle 2 approached 10 EMA to make Higher Low(HL)" - and candle 2 is the
    entry. Same location, opposite meaning, decided by which way the lows are
    stepping.
    """
    return "HL" if structure_intact(low, i, lookback) else "LL"


def zone_at(bar_low: float, bar_close: float, e10: float, e20: float,
            e50: float, tol: float | None = None) -> str | None:
    """Which named zone this bar is sitting in, or None.

    M10 takes priority: if the bar reached the 10 EMA that is the setup he
    names, even though such a bar is also technically inside the 10/20 band.
    """
    t = PARAMS["ZONE_TOL"] if tol is None else tol
    if e10 and abs(bar_low - e10) / e10 <= t and bar_close >= e10 * (1 - t):
        return "M10"
    if e20 and e10 and e20 < bar_low <= e10 * (1 + t):
        return "V12"                       # DERIVED
    if e50 and e20 and e50 < bar_low <= e20 * (1 + t):
        return "V25"                       # DERIVED
    return None


def dc_low(low: pd.Series, open_: pd.Series, close: pd.Series,
           i: int, back: int = 12) -> float | None:
    """The demand candle's low - where the stop goes.

    "enter above the marked green line with SL below the DC candle's low". Walk
    back for the most recent bar that turned the price with a real body; fall
    back to the lowest low of the window, which is still a structural level,
    rather than returning nothing and discarding a setup over a definition.
    """
    lo = max(1, i - back)
    for j in range(i, lo, -1):
        if j >= len(low) - 1:
            continue
        rng = float(max(close.iloc[j], open_.iloc[j]) - low.iloc[j])
        if rng <= 0:
            continue
        body = abs(float(close.iloc[j] - open_.iloc[j]))
        turned = low.iloc[j] <= low.iloc[j - 1] and low.iloc[j] <= low.iloc[j + 1]
        if turned and body / rng >= 0.35:
            return float(low.iloc[j])
    return float(low.iloc[lo: i + 1].min()) if i >= lo else None


def find_entry(df: pd.DataFrame, signal_i: int, params: dict | None = None,
               pre: dict | None = None) -> dict | None:
    """Wait for one of his triggers in the bars after a scan hit.

    Two triggers, both from the PDFs:

    A - the cross sequence, stated as a sequence in the Kalyan weekly section:
        "a big candle on high volumes closing above both 10 and 20 EMA and also
        led to 10 crossing above 20 EMA, after which we had an Inside Bar
        closing above 10 and 20 EMA, that was the buy point". The inside bar is
        the trigger, not the big candle - buying the big candle is buying the
        momentum he keeps refusing.

    B - the IB in a zone, from the Monthly section: an inside bar at the 10 EMA
        with the approach flipping from lower lows to a higher low.

    Returns None if nothing fires inside the wait window, which is itself the
    answer: most scan hits never become entries. "if you do not get the price
    at the best price, you're better off leaving it."
    """
    p = {**PARAMS, **(params or {})}
    o, h, l, c, v = (df[k] for k in ("open", "high", "low", "close", "volume"))
    e = pre["emas"] if pre and "emas" in pre else emas(c)
    e10, e20, e50 = e["ema10"], e["ema20"], e["ema50"]
    vmed = pre["vmed"] if pre and "vmed" in pre else v.rolling(20, min_periods=10).median()

    ret = c.pct_change() * 100
    last = min(len(df) - 2, signal_i + p["MAX_WAIT_BARS"])
    cross_seen = False

    for i in range(signal_i, last + 1):
        above_both = bool(c.iloc[i] > e10.iloc[i] and c.iloc[i] > e20.iloc[i])

        # --- Trigger A, part one: the big high-volume candle that crosses ---
        if (ret.iloc[i] >= p["BIG_CANDLE_PCT"] and above_both
                and v.iloc[i] >= p["VOL_MULT"] * (vmed.iloc[i] or np.inf)
                and e10.iloc[i] > e20.iloc[i]):
            cross_seen = True
            continue

        # --- Trigger A, part two: the inside bar that follows it ---
        if cross_seen and inside_bar(h, l, i) and above_both:
            return _entry(df, i, "A_cross_then_IB", zone_at(
                float(l.iloc[i]), float(c.iloc[i]),
                float(e10.iloc[i]), float(e20.iloc[i]), float(e50.iloc[i])), p, signal_i)

        # --- Trigger B: an inside bar in a named zone, on a higher low ---
        z = zone_at(float(l.iloc[i]), float(c.iloc[i]),
                    float(e10.iloc[i]), float(e20.iloc[i]), float(e50.iloc[i]))
        if z and inside_bar(h, l, i) and approach_mode(l, i) == "HL":
            # M10 additionally requires the structure to have survived the
            # pullback - the failure case the Kalyan study calls out by name.
            if z == "M10" and not structure_intact(l, i):
                continue
            return _entry(df, i, f"B_IB_at_{z}", z, p, signal_i)

    return None


def _entry(df, i, trigger, zone, p, signal_i) -> dict:
    o, h, l, c = (df[k] for k in ("open", "high", "low", "close"))
    entry_i = i + 1
    entry = float(c.iloc[entry_i]) if entry_i < len(df) else float(c.iloc[i])
    piv = dc_low(l, o, c, i)
    stop = piv * (1 - p["STOP_BUFFER"]) if piv and piv < entry else None
    return {
        "entry_i": entry_i,
        "trigger": trigger,
        "zone": zone,
        "entry": entry,
        "stop": stop,
        "risk_pct": (entry - stop) / entry * 100 if stop else None,
        "bars_waited": entry_i - signal_i,
    }
