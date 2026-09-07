"""Point-in-time feature engine for the champion-pullback study.

Every column produced here is computable from bars up to and including the row's
own date.  Nothing reads a future bar.  Two constructs need care and are handled
explicitly:

* swing points are fractals and are only *confirmed* three bars later, so the
  confirmed-swing columns carry the value that was knowable on that date, not
  the value the chart shows in hindsight;
* weekly aggregates use completed weeks only — the current, still-forming week
  is never read (the defect the earlier audit found in the production engine).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

SWING_K = 3          # fractal half-width; a swing is confirmed SWING_K bars later
AVWAP_LOOKBACK = 60  # bars searched for the anchor (swing high of the base)


# --------------------------------------------------------------------------- #
# data access
# --------------------------------------------------------------------------- #

def load_candles(db_path: str) -> dict[str, pd.DataFrame]:
    """Return {symbol: OHLCV frame indexed by date}, ascending, de-duplicated."""
    con = sqlite3.connect(db_path)
    try:
        raw = pd.read_sql_query(
            "SELECT symbol, dt, open, high, low, close, volume FROM candles "
            "ORDER BY symbol, dt",
            con,
        )
    finally:
        con.close()
    raw["dt"] = pd.to_datetime(raw["dt"])
    out: dict[str, pd.DataFrame] = {}
    for sym, grp in raw.groupby("symbol", sort=True):
        df = grp.drop(columns=["symbol"]).set_index("dt").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
        if len(df) >= 260:
            out[sym] = df
    return out


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #

def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _anchored_vwap(df: pd.DataFrame, lookback: int) -> pd.Series:
    """VWAP anchored to the highest-high bar of the trailing `lookback` window.

    The video anchors to "the swing high of the base" and then nudges the anchor
    by eye.  The nudging is not codable; the highest high of the recent base is
    the deterministic reading of the same instruction.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (tp * df["volume"]).to_numpy(dtype=float)
    vol = df["volume"].to_numpy(dtype=float)
    cum_pv = np.concatenate([[0.0], np.cumsum(pv)])
    cum_v = np.concatenate([[0.0], np.cumsum(vol)])
    highs = df["high"].to_numpy(dtype=float)

    n = len(df)
    out = np.full(n, np.nan)
    for i in range(n):
        lo = max(0, i - lookback + 1)
        a = lo + int(np.argmax(highs[lo : i + 1]))
        v = cum_v[i + 1] - cum_v[a]
        if v > 0:
            out[i] = (cum_pv[i + 1] - cum_pv[a]) / v
    return pd.Series(out, index=df.index)


def _confirmed_swings(df: pd.DataFrame, k: int = SWING_K) -> pd.DataFrame:
    """Last and previous confirmed swing high/low, as known on each date.

    Bar i is a swing high if its high is the maximum of [i-k, i+k]; that fact is
    only known at bar i+k, so the value is published from i+k onwards.
    """
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(df)
    last_sh = np.full(n, np.nan)
    prev_sh = np.full(n, np.nan)
    last_sl = np.full(n, np.nan)
    prev_sl = np.full(n, np.nan)
    sh_val = sh_prev = sl_val = sl_prev = np.nan

    for i in range(n):
        pivot = i - k                       # bar whose fractal status closes now
        if pivot - k >= 0:
            w_hi = high[pivot - k : pivot + k + 1]
            w_lo = low[pivot - k : pivot + k + 1]
            if high[pivot] == w_hi.max():
                sh_prev, sh_val = sh_val, high[pivot]
            if low[pivot] == w_lo.min():
                sl_prev, sl_val = sl_val, low[pivot]
        last_sh[i], prev_sh[i] = sh_val, sh_prev
        last_sl[i], prev_sl[i] = sl_val, sl_prev

    return pd.DataFrame(
        {
            "swing_high": last_sh,
            "swing_high_prev": prev_sh,
            "swing_low": last_sl,
            "swing_low_prev": prev_sl,
        },
        index=df.index,
    )


def _unfilled_gap_base(df: pd.DataFrame, max_age: int = 60) -> pd.Series:
    """Base of the most recent still-unfilled up-gap (the video's 'unfilled gap').

    A gap-up on bar g leaves the zone [high[g-1], low[g]] untraded.  It stays
    unfilled while no later low pierces high[g-1].  The level published is the
    gap base, which is where a pullback "closes the gap".
    """
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(df)
    out = np.full(n, np.nan)
    base = np.nan
    age = 0
    for i in range(n):
        if not np.isnan(base):
            age += 1
            if low[i] <= base or age > max_age:
                base = np.nan
        if i > 0 and low[i] > high[i - 1]:
            base, age = high[i - 1], 0
        out[i] = base
    return pd.Series(out, index=df.index)


def _weekly_pit(df: pd.DataFrame) -> pd.DataFrame:
    """Weekly EMA9/EMA21 and weekly close, using completed weeks only."""
    wk = df.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    if len(wk) < 25:
        return pd.DataFrame(index=df.index, columns=["w_close", "w_ema9", "w_ema21"], dtype=float)
    feats = pd.DataFrame(
        {
            "w_close": wk["close"],
            "w_ema9": _ema(wk["close"], 9),
            "w_ema21": _ema(wk["close"], 21),
        }
    )
    # shift one week: a daily bar inside week W may only read through week W-1
    feats = feats.shift(1)
    return feats.reindex(df.index, method="ffill")


# --------------------------------------------------------------------------- #
# per-symbol feature frame
# --------------------------------------------------------------------------- #

def build_features(df: pd.DataFrame, avwap_lookback: int = AVWAP_LOOKBACK) -> pd.DataFrame:
    f = df.copy()
    c = f["close"]
    f["ema9"] = _ema(c, 9)
    f["ema21"] = _ema(c, 21)
    f["ema50"] = _ema(c, 50)
    f["ema150"] = _ema(c, 150)
    f["atr14"] = _atr(f)
    f["adr20"] = ((f["high"] / f["low"] - 1.0) * 100).rolling(20).mean()
    f["dollar_vol"] = c * f["volume"]
    f["dv20"] = f["dollar_vol"].rolling(20).median()
    f["relvol"] = f["volume"] / f["volume"].rolling(50).mean()
    f["avwap"] = _anchored_vwap(f, avwap_lookback)
    f["ret63"] = c / c.shift(63) - 1.0
    f["ret21"] = c / c.shift(21) - 1.0
    f["high20"] = f["high"].rolling(20).max()
    f["low20"] = f["low"].rolling(20).min()
    f["high60"] = f["high"].rolling(60).max()
    f["ema21_slope"] = f["ema21"] / f["ema21"].shift(5) - 1.0
    f["ema50_slope"] = f["ema50"] / f["ema50"].shift(10) - 1.0
    f["range"] = (f["high"] - f["low"]).replace(0, np.nan)
    f["close_pos"] = (c - f["low"]) / f["range"]          # 1 = closed on the high
    f = pd.concat([f, _confirmed_swings(f)], axis=1)
    f["gap_base"] = _unfilled_gap_base(f)
    f = pd.concat([f, _weekly_pit(f)], axis=1)
    # bars since the most recent 20-day high / low (how fresh the leg is)
    for col, src, cmp_col in (("bars_since_high20", "high", "high20"),
                              ("bars_since_low20", "low", "low20")):
        if cmp_col == "high20":
            flags = (f["high"] >= f[cmp_col] - 1e-9).to_numpy()
        else:
            flags = (f["low"] <= f[cmp_col] + 1e-9).to_numpy()
        since = np.full(len(f), 9999)
        last = -1
        for i, flag in enumerate(flags):
            if flag:
                last = i
            since[i] = 9999 if last < 0 else i - last
        f[col] = since
    return f


@dataclass
class Market:
    """Equal-weighted proxy index built from the traded universe itself.

    The candle store holds no index series, so the market filter is reconstructed
    from the constituents.  Each day's return is the cross-sectional mean of the
    constituents' returns — an equal-weighted index, not the Nifty 500.
    """

    index: pd.DataFrame          # level, ema9/21/50, breadth
    dates: pd.DatetimeIndex


def build_market(feats: dict[str, pd.DataFrame]) -> Market:
    rets, above50 = {}, {}
    for sym, f in feats.items():
        rets[sym] = f["close"].pct_change()
        above50[sym] = (f["close"] > f["ema50"]).where(f["ema50"].notna())
    ret = pd.DataFrame(rets).mean(axis=1).fillna(0.0)
    breadth = pd.DataFrame(above50).mean(axis=1)
    level = (1.0 + ret).cumprod() * 1000.0
    idx = pd.DataFrame({"level": level, "breadth50": breadth})
    idx["ema9"] = _ema(idx["level"], 9)
    idx["ema21"] = _ema(idx["level"], 21)
    idx["ema50"] = _ema(idx["level"], 50)
    idx["ema21_slope"] = idx["ema21"] / idx["ema21"].shift(5) - 1.0
    idx["ret21"] = idx["level"] / idx["level"].shift(21) - 1.0
    idx["ret63"] = idx["level"] / idx["level"].shift(63) - 1.0
    idx["vol21"] = idx["level"].pct_change().rolling(21).std() * np.sqrt(252)
    return Market(index=idx, dates=idx.index)


def cross_sectional_rs(feats: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Percentile rank (0-100) of 63-day return across the universe, per date."""
    frame = pd.DataFrame({sym: f["ret63"] for sym, f in feats.items()})
    return frame.rank(axis=1, pct=True) * 100.0
