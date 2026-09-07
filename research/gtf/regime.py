"""Market regime, computed point-in-time from the universe itself.

The structural weakness in everything built so far is that it is long-only.
The candidate pool averages +1.10 R in 2022-23 and -0.15 R over the last two
years, and no ranking rule reverses that - ranking only decides how much of a
bad stretch you take. The cheap version of the fix is not to be long when
long does not work.

Three regime measures, all read on the day they are used and all built from
the same Nifty 500 daily store, so nothing external is needed:

  trend    equal-weight index above its own 200-day average
  breadth  share of the universe trading above its own 200-day average
  vol      20-day realised volatility of the index against its own median

Breadth is the one to watch. An index can be dragged up by a few large names
while most stocks are falling, and a long book made of ordinary names lives
in the second world, not the first.
"""
from __future__ import annotations
import sqlite3
import numpy as np, pandas as pd


def build(db, min_names=100):
    con = sqlite3.connect(db)
    px = pd.read_sql_query("SELECT dt, symbol, close FROM candles", con)
    con.close()
    px["dt"] = pd.to_datetime(px["dt"])
    wide = px.pivot_table(index="dt", columns="symbol", values="close").sort_index()

    # equal-weight index from daily cross-sectional mean return
    idx = (wide / wide.shift(1)).mean(axis=1).fillna(1.0).cumprod()
    sma200 = idx.rolling(200, min_periods=200).mean()
    sma50 = idx.rolling(50, min_periods=50).mean()

    above = wide > wide.rolling(200, min_periods=200).mean()
    valid = wide.rolling(200, min_periods=200).mean().notna()
    breadth = (above & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
    breadth[valid.sum(axis=1) < min_names] = np.nan

    ret = idx.pct_change()
    vol20 = ret.rolling(20).std() * np.sqrt(252) * 100
    # compare against the past only, never a full-sample median
    vol_med = vol20.expanding(min_periods=250).median()

    ema20 = idx.ewm(span=20, adjust=False).mean()
    ema50 = idx.ewm(span=50, adjust=False).mean()
    # distance of the index from its own 20/50 EMA, in percent and in units of
    # the index's own daily volatility, so "near" means the same thing in a
    # calm market and a wild one
    isd = idx.pct_change().rolling(20).std() * 100
    swing_low = idx.rolling(60, min_periods=60).min()

    r = pd.DataFrame({
        "idx_from_ema20": 100 * (idx / ema20 - 1),
        "idx_from_ema50": 100 * (idx / ema50 - 1),
        "idx_from_ema20_sd": (100 * (idx / ema20 - 1)) / isd,
        "idx_from_ema50_sd": (100 * (idx / ema50 - 1)) / isd,
        "idx_above_ema20": (idx > ema20).astype(float),
        "idx_above_ema50": (idx > ema50).astype(float),
        # how far above the last 60-day low the index is - "at support" means small
        "idx_above_60d_low": 100 * (idx / swing_low - 1),
        "idx": idx,
        "idx_above_200": (idx > sma200).astype(float),
        "idx_above_50": (idx > sma50).astype(float),
        "idx_slope_200": 100 * (sma200 / sma200.shift(20) - 1),
        "breadth": 100 * breadth,
        "breadth_ma20": 100 * breadth.rolling(20).mean(),
        "vol20": vol20,
        "vol_high": (vol20 > vol_med).astype(float),
    })
    r.loc[sma200.isna(), ["idx_above_200", "idx_slope_200"]] = np.nan
    return r
