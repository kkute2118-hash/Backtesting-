"""Indicator maths, pinned.

The migration's one hard requirement is that the same inputs produce the same
scanner results as before. These tests pin the primitives everything else is
built from, so a future refactor of the engine cannot quietly change what the
scanner returns without a test failing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine import core


def test_ema_matches_pandas_ewm():
    series = pd.Series([10.0, 11, 12, 11, 13, 15, 14, 16, 18, 17, 19, 20])
    expected = series.ewm(span=5, adjust=False, min_periods=5).mean()
    pd.testing.assert_series_equal(core.ema(series, 5), expected)


def test_ema_warmup_is_nan_not_zero():
    """A partially-warmed EMA must be NaN. Zero would read as a real level and
    make every "close >= EMA" rule pass on a stock's first days."""
    series = pd.Series(np.arange(1, 11, dtype=float))
    assert core.ema(series, 5).iloc[:4].isna().all()
    assert np.isfinite(core.ema(series, 5).iloc[4])


def test_sma_matches_rolling_mean():
    series = pd.Series(np.arange(1, 21, dtype=float))
    pd.testing.assert_series_equal(core.sma(series, 5),
                                   series.rolling(5, min_periods=5).mean())


def test_rsi_stays_in_range_and_bottoms_at_zero():
    rising = pd.Series(np.arange(1, 60, dtype=float))
    falling = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert core.rsi(rising).dropna().between(0, 100).all()
    assert core.rsi(falling).iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_rsi_is_undefined_when_there_is_no_average_loss():
    """Documents current behaviour, which is not the textbook one.

    ``rsi()`` divides by ``dn.replace(0, np.nan)``, so a window with no down
    days yields NaN instead of 100. Every "RSI >= 50" gate therefore evaluates
    False for a stock in an unbroken run of up bars. It is pinned here rather
    than fixed because changing it would change which stocks the scanner
    returns, which this migration deliberately does not do.
    """
    rising = pd.Series(np.arange(1, 60, dtype=float))
    assert np.isnan(core.rsi(rising).iloc[-1])


def test_rsi_known_value():
    """Wilder-style RSI on a fixed series — the number itself, not a property."""
    closes = pd.Series([44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
                        45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28])
    assert core.rsi(closes, 14).iloc[-1] == pytest.approx(50.657, abs=0.01)


def test_atr_is_positive_and_matches_true_range(frames):
    df = frames["TRENDUP"]
    atr = core._atr(df, 14).dropna()
    assert (atr > 0).all()
    tr = pd.concat([df.high - df.low,
                    (df.high - df.close.shift()).abs(),
                    (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    pd.testing.assert_series_equal(atr, tr.rolling(14).mean().dropna(),
                                   check_names=False)


def test_features_fast_has_the_columns_the_dsl_advertises(frames):
    """Every column the custom-strategy DSL whitelists must actually exist —
    otherwise a rule the UI accepts raises KeyError at scan time."""
    f = core.features_fast("TRENDUP", frames["TRENDUP"])
    missing = core.CUSTOM_DSL_COLUMNS - set(f.columns)
    assert not missing, f"DSL advertises columns the feature frame lacks: {missing}"


def test_features_are_deterministic(frames):
    a = core.features_fast("DETERMINISM_A", frames["TRENDUP"])
    b = core.features_fast("DETERMINISM_B", frames["TRENDUP"])
    pd.testing.assert_frame_equal(a, b)


def test_daily_and_weekly_features_do_not_depend_on_later_bars(frames):
    """Truncating the frame must not change the features of the bars that remain."""
    df = frames["TRENDUP"]
    full = core.features_fast("ASOF_FULL", df)
    truncated = core.features_fast("ASOF_TRUNC", df.iloc[:-40])
    common = truncated.index
    for column in ("ema10", "ema20", "ema50", "ema200", "rsi14", "atr14",
                   "relvol", "vol20", "wrsi14", "wema20", "wema50", "wclose"):
        pd.testing.assert_series_equal(
            full.loc[common, column], truncated[column], check_names=False,
            rtol=1e-9, atol=1e-9,
        )


def test_monthly_features_use_the_whole_calendar_month(frames):
    """Documents a real limitation, so a future fix has to be deliberate.

    ``features_fast`` aggregates each calendar month in one pass and maps that
    single value onto every daily row inside it. For the current month that is
    correct - the partial month is all that exists - and the live scanner is
    therefore sound. For a *historical* bar it means the monthly columns carry
    that month's eventual close and high, which the bar could not have known.
    Any backtest or learning observation that leans on a monthly gate inherits
    that, so its results read optimistically.

    Pinned rather than corrected: fixing it changes every stored backtest and
    learning row, which is an engine decision, not a UI migration's to make.
    """
    df = frames["TRENDUP"]
    f = core.features_fast("MONTHLY_ASOF", df)
    month_key = df.index.to_period("M")
    month = month_key[400]
    bars = df[month_key == month]
    assert len(bars) > 5

    first_bar = bars.index[0]
    assert f.loc[first_bar, "mclose"] == pytest.approx(float(bars.close.iloc[-1]))
    assert f.loc[first_bar, "mhigh"] == pytest.approx(float(bars.high.max()))
