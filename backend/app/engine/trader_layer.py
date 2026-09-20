"""Second-stage selection over scanner output, from the lecture methodology.

The scanners (S1-S5) decide WHAT is a candidate. Nothing here touches that.
This module reads their output and answers a different question: of the
candidates, which ones would the author of the transcripts actually trade, at
what price, and with what stop.

Two tiers, kept apart on purpose:

  hard gates   rules he states as requirements and that compute exactly from
               OHLCV. These reject.
  soft signals approximations of his judgement calls. These rank, never reject.

Anything with no number in the transcripts is a parameter here, not a
constant, and lives in PARAMS so a sweep can see it. He states relationships
and refuses to state numbers - "Do not make it a formula. If you do, you are
in trouble" - so a hard-coded threshold in this file would be ours wearing his
name.

Reference: research/trader_methodology/
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Constants the transcripts actually state. Not tunable.
# --------------------------------------------------------------------------

# Lecture 12, twice: "almost 250 crores on an average for the 20 days" and
# "80 crores average turnover last 20 days". The only two places in the corpus
# where a lookback is named, and both say 20. Our own 21-day turnover window is
# a separate setting elsewhere and stays separate.
AUTHOR_AVERAGE_TURNOVER_LOOKBACK = 20

EMA_PERIODS = (10, 20, 50, 200)

# Lecture 12: a big red candle has to be answered by an up candle that takes
# back at least half of it, ideally the whole. Below that, "the immediate
# left-hand side is showing you selling pressure".
COUNTER_RATIO_MIN = 0.5

# --------------------------------------------------------------------------
# Everything below is fitted by us. Sweep it; do not trust a default.
# --------------------------------------------------------------------------

PARAMS = {
    # CB - see cb_flags(). The percentile of the stock's own positive days
    # above which a day counts as "performing extremely well compared to other
    # days' good moves".
    "CB_PERCENTILE": 80.0,
    "CB_DARK_PERCENTILE": 90.0,
    "CB_LOOKBACK": 250,

    "TURNOVER_FLOOR_CR": 40.0,      # our existing filter's floor, as a starting point
    "MIN_EMA_SEP": 0.010,           # "clearly visible distance" between 10 and 20
    "EVENT_LOOKBACK": 60,           # how far back an event on the LHS still counts
    "HOLD_BARS": 5,                 # bars the 10-over-20 configuration must survive
    "EXPANSION_LOOKBACK": 60,       # window for locating the expansion-ending bar
    "VOLUME_ELEVATION_MULT": 1.5,   # volume vs its own trailing median
    "CLUSTER_MIN_FRACTION": 0.30,   # share of expansion bars that must be elevated
    "STOP_BUFFER": 0.005,           # below the pivot low
    "MAX_RISK_PCT": 0.10,           # widest stop we will still call tradeable
}


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def emas(close: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({f"ema{n}": _ema(close, n) for n in EMA_PERIODS}, index=close.index)


# --------------------------------------------------------------------------
# CB - the candle class the author colours blue
# --------------------------------------------------------------------------

def cb_flags(close: pd.Series, params: dict | None = None) -> pd.DataFrame:
    """Mark the days the author would colour blue.

    A CB is a day the stock performed extremely well *compared with its own
    other good days* - so the benchmark is the stock's own distribution of
    positive daily returns, not a fixed percentage. That is why he can call a
    6% day a CB in one stock and unremarkable in another, and why CB sits
    beside DNA and relativity in his own list ("the DNA of ETF, CB of ETF,
    relativity of ETF") rather than beside volume.

    The threshold is a trailing percentile, so it is causal and it adapts as a
    stock's character changes. Two bands, because he distinguishes blue from
    dark/navy blue and appears to mean degree.

    Volume is deliberately not part of this. He assesses volume separately as
    cluster-versus-tower, and folding it in here would double-count it in any
    ranking that uses both.
    """
    p = {**PARAMS, **(params or {})}
    ret = close.pct_change() * 100.0
    pos = ret.where(ret > 0)

    def _pct(level):
        return pos.rolling(p["CB_LOOKBACK"], min_periods=40).quantile(level / 100.0)

    lo = _pct(p["CB_PERCENTILE"])
    hi = _pct(p["CB_DARK_PERCENTILE"])
    return pd.DataFrame(
        {
            "ret_pct": ret,
            "cb_threshold": lo,
            "is_cb": (ret >= lo) & ret.notna() & lo.notna(),
            "is_cb_dark": (ret >= hi) & ret.notna() & hi.notna(),
        },
        index=close.index,
    )


def cb_run_quality(cb: pd.DataFrame, start: int, end: int) -> dict:
    """How blue an expansion is.

    He counts them - "look at how many dark blue candles you are having, 1 2 3
    4" - and he rejects expansions with white candles interleaved: "Are there
    any white candles in between? ... No. In fact, every single candle of the
    expansion is a blue shade colour candle."

    So both the count and the *purity* matter, and they are reported
    separately rather than blended.
    """
    lo, hi = max(start, 0), min(end, len(cb) - 1)
    if hi < lo:
        return {"cb_count": 0, "cb_dark_count": 0, "cb_purity": 0.0, "up_bars": 0}
    window = cb.iloc[lo : hi + 1]
    up = window[window["ret_pct"] > 0]
    n_up = int(len(up))
    n_cb = int(up["is_cb"].sum())
    return {
        "cb_count": n_cb,
        "cb_dark_count": int(up["is_cb_dark"].sum()),
        # Share of the *up* bars that were CBs. White candles in the expansion
        # are exactly the up bars that were not.
        "cb_purity": float(n_cb / n_up) if n_up else 0.0,
        "up_bars": n_up,
    }


# --------------------------------------------------------------------------
# Turnover - where the money actually is
# --------------------------------------------------------------------------

def turnover_cr(close: pd.Series, volume: pd.Series) -> pd.Series:
    return close * volume / 1e7


def turnover_frame(close: pd.Series, volume: pd.Series) -> pd.DataFrame:
    """Daily turnover, its 20-day average, the spike ratio and the drift.

    The drift is the part most people miss and the author dwells on: he walks
    a stock forward and reads the *average* climbing, 175 to 200 to 255 to 600.
    A single huge day that leaves the average flat is the turnover version of a
    single tower of volume - money passed through, it did not arrive.
    """
    t = turnover_cr(close, volume)
    avg = t.rolling(AUTHOR_AVERAGE_TURNOVER_LOOKBACK,
                    min_periods=AUTHOR_AVERAGE_TURNOVER_LOOKBACK).mean()
    return pd.DataFrame(
        {
            "turnover_cr": t,
            "avg_turnover_20": avg,
            "turnover_spike": t / avg,
            "turnover_drift": avg / avg.shift(AUTHOR_AVERAGE_TURNOVER_LOOKBACK) - 1.0,
        },
        index=close.index,
    )


def volume_cluster(volume: pd.Series, start: int, end: int, params=None) -> dict:
    """Cluster or single tower.

    "this is a single Tower of volume, there is no good volume before that or
    after that; there are good volume clusters that you see here which are
    absent." The discriminator is persistence across adjacent bars, not the
    height of any one bar - so this counts elevated bars and reports the share,
    and flags the isolated-spike case separately.

    The elevation multiple has no transcript value and is a parameter.
    """
    p = {**PARAMS, **(params or {})}
    lo, hi = max(start, 0), min(end, len(volume) - 1)
    if hi < lo:
        return {"cluster_fraction": 0.0, "single_tower": True, "elevated_bars": 0}
    base = volume.rolling(AUTHOR_AVERAGE_TURNOVER_LOOKBACK, min_periods=10).median()
    window = volume.iloc[lo : hi + 1]
    ref = base.iloc[lo : hi + 1]
    elevated = (window >= ref * p["VOLUME_ELEVATION_MULT"]).fillna(False)
    n = int(elevated.sum())
    frac = float(n / len(window)) if len(window) else 0.0
    return {
        "cluster_fraction": frac,
        "elevated_bars": n,
        "single_tower": bool(n <= 1 and len(window) >= 4),
    }


# --------------------------------------------------------------------------
# Event on the LHS - his primary filter
# --------------------------------------------------------------------------

def event_frame(close: pd.Series, params=None) -> pd.DataFrame:
    """Crossovers, whether they held, and how compressed the averages are.

    Lecture 7 is the whole reason `event_held` exists. Two areas of one chart
    looked alike; in the first an up move crossed the averages and "all the
    hard work was undone by the horrible contraction", in the second the
    configuration survived and the stock made the largest move it ever had. A
    cross that reverted is not an event.
    """
    p = {**PARAMS, **(params or {})}
    e = emas(close)
    up = e["ema10"] > e["ema20"]
    cross = up & ~up.shift(1).fillna(False)
    return pd.DataFrame(
        {
            "cross_10_20": cross,
            "bars_since_cross": _bars_since(cross),
            "event_held": up.rolling(p["HOLD_BARS"], min_periods=p["HOLD_BARS"]).min().astype(bool),
            "ema_sep": (e["ema10"] - e["ema20"]).abs() / close,
            "ema_compression": (e.max(axis=1) - e.min(axis=1)) / close,
            "stacked": (e["ema10"] > e["ema20"]) & (e["ema20"] > e["ema50"]),
            "above_ema10": close > e["ema10"],
        },
        index=close.index,
    ).join(e)


def _bars_since(flag: pd.Series) -> pd.Series:
    idx = np.arange(len(flag))
    last = np.where(flag.to_numpy(), idx, np.nan)
    last = pd.Series(last, index=flag.index).ffill()
    return (pd.Series(idx, index=flag.index) - last)


# --------------------------------------------------------------------------
# Expansion and contraction structure
# --------------------------------------------------------------------------

def expansion_end(close: pd.Series, i: int, params=None) -> int:
    """Causal stand-in for "the candle with which the expansion ended".

    He picks it by eye, after the fact. The highest close in a trailing window,
    fixed as of bar i and never revised, is the honest causal substitute: a
    different definition doing the same job. The truncation check in
    BACKTEST_SPEC exists to catch it if it ever stops being causal.
    """
    p = {**PARAMS, **(params or {})}
    lo = max(0, i - p["EXPANSION_LOOKBACK"])
    if i <= lo:
        return lo
    return lo + int(np.argmax(close.iloc[lo : i + 1].to_numpy()))


def structure_at(high: pd.Series, low: pd.Series, close: pd.Series,
                 i: int, params=None) -> dict:
    """Containment and the upper-half rule, evaluated at bar i only.

    Lecture 4, on the contraction staying inside the high of the bar the
    expansion ended on and in the upper half of its range: "this is one of the
    most important points that I'll ever give you in your trading." It is also
    the one major structural rule that computes exactly, with no parameter
    beyond locating the expansion bar.
    """
    end = expansion_end(close, i, params)
    if end >= i:
        return {"expansion_end": end, "contained": True, "upper_half": True,
                "contraction_bars": 0, "drawdown_from_high": 0.0}
    seg_h = high.iloc[end + 1 : i + 1]
    seg_l = low.iloc[end + 1 : i + 1]
    hi_bar, lo_bar = float(high.iloc[end]), float(low.iloc[end])
    mid = (hi_bar + lo_bar) / 2.0
    return {
        "expansion_end": end,
        "contained": bool(seg_h.max() <= hi_bar),
        "upper_half": bool(seg_l.min() >= mid),
        "contraction_bars": int(i - end),
        "drawdown_from_high": float((hi_bar - seg_l.min()) / hi_bar) if hi_bar else 0.0,
    }


def counter_ok(open_: pd.Series, close: pd.Series, start: int, end: int) -> bool:
    """Has every oversized red candle in the contraction been answered?

    Lecture 12: candles hovering below half of a big red candle mean the
    immediate left-hand side is still showing selling pressure, so wait for a
    candle that eats it. Here "oversized" means bigger than the largest up
    candle of the run it is correcting.
    """
    lo, hi = max(start, 0), min(end, len(close) - 1)
    if hi <= lo:
        return True
    body = (close - open_).abs()
    seg = slice(lo, hi + 1)
    ups = body.iloc[seg][close.iloc[seg] > open_.iloc[seg]]
    ref = float(ups.max()) if len(ups) else 0.0
    if ref <= 0:
        return True
    for j in range(lo, hi + 1):
        if close.iloc[j] >= open_.iloc[j] or body.iloc[j] <= ref:
            continue
        later = body.iloc[j + 1 : hi + 1][close.iloc[j + 1 : hi + 1] > open_.iloc[j + 1 : hi + 1]]
        if not len(later) or float(later.max()) < COUNTER_RATIO_MIN * float(body.iloc[j]):
            return False
    return True


# --------------------------------------------------------------------------
# Pivot and risk - the part he says the edge lives in
# --------------------------------------------------------------------------

def pivot_low(low: pd.Series, close: pd.Series, open_: pd.Series,
              i: int, params=None) -> float | None:
    """The demand-candle low the stop belongs under.

    Walks back from bar i for the most recent up candle with a real body and a
    lower low than its neighbours - his DC. Returns None when there is no such
    bar, and None is a rejection, not a missing value: "if you don't have a
    quality demand area, demand pivot on your ILHS, it gets really difficult to
    allocate risk to this trade, because well, where do I put my SL?"
    """
    p = {**PARAMS, **(params or {})}
    start = max(1, i - p["EXPANSION_LOOKBACK"])
    best = None
    for j in range(i, start, -1):
        if j <= 0 or j >= len(low) - 1:
            continue
        rng = float(high_low_range(low, close, open_, j))
        if rng <= 0:
            continue
        body = abs(float(close.iloc[j]) - float(open_.iloc[j]))
        turned = float(low.iloc[j]) <= float(low.iloc[j - 1]) and float(low.iloc[j]) <= float(low.iloc[j + 1])
        if turned and body / rng >= 0.4:
            best = float(low.iloc[j])
            break
    return best


def high_low_range(low: pd.Series, close: pd.Series, open_: pd.Series, j: int) -> float:
    hi = max(float(close.iloc[j]), float(open_.iloc[j]))
    return hi - float(low.iloc[j])


def risk_pct(entry: float, pivot: float, params=None) -> float:
    p = {**PARAMS, **(params or {})}
    stop = pivot * (1.0 - p["STOP_BUFFER"])
    return float((entry - stop) / entry) if entry else np.inf


def ma_proximity(open_: float, close_: float, ma: float) -> tuple[float, float]:
    """Lecture 5's four scenarios, as two numbers.

    Case 2 - both small - is the one he wants. Opening near the average puts
    the pivot close by so the stop is tight; closing near it leaves no room for
    volatility, which is what lets a contraction candle form at the average at
    all instead of the price having to travel back down to it.
    """
    if not ma:
        return np.inf, np.inf
    return abs(open_ - ma) / ma, abs(close_ - ma) / ma


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------

HARD_GATES = ("liquidity", "event", "separation", "stacked",
              "contained", "upper_half", "counter", "pivot", "risk")


def evaluate(frame: pd.DataFrame, i: int, params: dict | None = None,
             precomputed: dict | None = None) -> dict:
    """Judge one candidate bar. Returns the verdict plus every input to it.

    `i` is the signal bar. Everything read is at or before `i`; entry is priced
    at i+1 by the caller, the same convention the existing backtest uses.

    Returns `passed`, the first failing gate in `reject`, and the soft signals
    whether it passed or not - a rejected candidate's forward return is the
    cheapest check that the funnel is not inverted, and that needs its scores.
    """
    p = {**PARAMS, **(params or {})}
    o, h, l, c, v = (frame[k] for k in ("open", "high", "low", "close", "volume"))

    pre = precomputed or {}
    ev = pre.get("event") if pre.get("event") is not None else event_frame(c, p)
    tf = pre.get("turnover") if pre.get("turnover") is not None else turnover_frame(c, v)
    cb = pre.get("cb") if pre.get("cb") is not None else cb_flags(c, p)

    out: dict = {"index": i, "date": frame.index[i]}
    fail = []

    avg_t = float(tf["avg_turnover_20"].iloc[i]) if not pd.isna(tf["avg_turnover_20"].iloc[i]) else np.nan
    out["avg_turnover_20"] = avg_t
    out["turnover_spike"] = _f(tf["turnover_spike"].iloc[i])
    out["turnover_drift"] = _f(tf["turnover_drift"].iloc[i])
    if not (avg_t >= p["TURNOVER_FLOOR_CR"]):
        fail.append("liquidity")

    out["bars_since_cross"] = _f(ev["bars_since_cross"].iloc[i])
    out["event_held"] = bool(ev["event_held"].iloc[i])
    out["ema_sep"] = _f(ev["ema_sep"].iloc[i])
    out["ema_compression"] = _f(ev["ema_compression"].iloc[i])
    out["stacked"] = bool(ev["stacked"].iloc[i])

    since = out["bars_since_cross"]
    if not (since is not None and since <= p["EVENT_LOOKBACK"] and out["event_held"]):
        fail.append("event")
    if not (out["ema_sep"] is not None and out["ema_sep"] >= p["MIN_EMA_SEP"]):
        fail.append("separation")
    if not out["stacked"]:
        fail.append("stacked")

    st = structure_at(h, l, c, i, p)
    out.update(st)
    if not st["contained"]:
        fail.append("contained")
    if not st["upper_half"]:
        fail.append("upper_half")

    if not counter_ok(o, c, st["expansion_end"], i):
        fail.append("counter")

    piv = pivot_low(l, c, o, i, p)
    out["pivot"] = piv
    entry = float(c.iloc[i])
    out["entry_ref"] = entry
    if piv is None or piv >= entry:
        fail.append("pivot")
        out["risk_pct"] = None
    else:
        out["risk_pct"] = risk_pct(entry, piv, p)
        if out["risk_pct"] > p["MAX_RISK_PCT"]:
            fail.append("risk")

    # Soft signals. Computed for rejects too - see the docstring.
    out.update(cb_run_quality(cb, st["expansion_end"] - 10, st["expansion_end"]))
    out.update(volume_cluster(v, st["expansion_end"] - 10, st["expansion_end"], p))
    out["is_cb_signal"] = bool(cb["is_cb"].iloc[i])
    prox_o, prox_c = ma_proximity(float(o.iloc[i]), entry, float(ev["ema10"].iloc[i]))
    out["ma_prox_open"], out["ma_prox_close"] = _f(prox_o), _f(prox_c)

    out["passed"] = not fail
    out["reject"] = fail[0] if fail else None
    out["rejects"] = fail
    return out


def _f(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if (np.isnan(x) or np.isinf(x)) else x


def rank_score(v: dict, weights: dict | None = None) -> float:
    """Order the survivors. Ranking only - this never rejects.

    Risk distance leads because that is his own stated chain: tighter stop,
    bigger position, the trade is worth the slot. The rest are approximations
    of judgement calls and are weighted low until a backtest says otherwise.
    """
    w = {"risk": 1.0, "cb_purity": 0.4, "cluster": 0.3,
         "drift": 0.2, "prox": 0.3, "compression": 0.2, **(weights or {})}
    r = v.get("risk_pct")
    s = 0.0
    s += w["risk"] * (1.0 - min(r / PARAMS["MAX_RISK_PCT"], 1.0)) if r else 0.0
    s += w["cb_purity"] * float(v.get("cb_purity") or 0.0)
    s += w["cluster"] * min(float(v.get("cluster_fraction") or 0.0) / 0.5, 1.0)
    s += w["drift"] * min(max(float(v.get("turnover_drift") or 0.0), 0.0) / 0.5, 1.0)
    prox = v.get("ma_prox_close")
    s += w["prox"] * (1.0 - min(prox / 0.05, 1.0)) if prox is not None else 0.0
    comp = v.get("ema_compression")
    s += w["compression"] * (1.0 - min(comp / 0.15, 1.0)) if comp is not None else 0.0
    return float(s)
