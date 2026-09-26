"""S6 — fresh 50-day-high breakout with market breadth.

Pins the rules against hand-built bars: the breakout and its four-week
re-arm, the breadth gate (and that a missing breadth reading never passes),
the 52-week location rules, the ATR floor, and the exit that the backtest
chose the parameters with.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine import core


def _series_frame(closes, spread=0.03):
    """Daily bars around `closes`, high/low `spread` either side."""
    closes = np.asarray(closes, dtype=float)
    index = pd.bdate_range(end="2026-06-30", periods=len(closes))
    return pd.DataFrame({
        "open": closes, "high": closes * (1 + spread), "low": closes * (1 - spread),
        "close": closes, "volume": 1_000_000.0,
    }, index=index)


def _leader_breaking_out(bars=320):
    """A stock that doubled off its low, then based for 60 sessions, then breaks out."""
    rise = np.linspace(100, 200, bars - 61)
    base = np.full(60, 190.0)
    return _series_frame(np.concatenate([rise, base, [215.0]]))


def _with_breadth(x, value):
    out = x.copy()
    out[core.S6_BREADTH_COLUMN] = value
    return out


def test_fires_on_a_leader_breaking_out_in_a_broad_market():
    x = _with_breadth(_leader_breaking_out(), 0.6)
    sig = core.strategy_signal(x, 6)
    assert bool(sig.iloc[-1])
    assert sig.dtype == bool


def test_market_breadth_gate():
    x = _leader_breaking_out()
    assert not core.strategy_signal(_with_breadth(x, 0.49), 6).iloc[-1]
    assert core.strategy_signal(_with_breadth(x, core.S6_MIN_BREADTH), 6).iloc[-1]


def test_missing_breadth_never_qualifies():
    """Without attach_market_breadth() the gate reads NaN and must fail."""
    x = _leader_breaking_out()
    assert not core.strategy_signal(x, 6).any()
    assert not core.strategy_signal(_with_breadth(x, np.nan), 6).any()


def test_only_the_first_breakout_in_four_weeks_counts():
    x = _leader_breaking_out()
    closes = np.concatenate([x.close.to_numpy(), [225.0, 235.0]])
    y = _with_breadth(_series_frame(closes), 0.8)
    sig = core.strategy_signal(y, 6)
    assert sig.iloc[-3] and not sig.iloc[-2] and not sig.iloc[-1]


def test_needs_to_be_well_off_the_52_week_low():
    # Same shape but only 30% above the low: a bounce, not a leader.
    rise = np.linspace(160, 200, 259)
    x = _with_breadth(_series_frame(np.concatenate([rise, np.full(60, 190.0), [215.0]])), 0.8)
    m = core.strategy_condition_matrix(x, 6)
    assert m["Fresh 50-day-high breakout"].iloc[-1]
    assert not m[">= 60% above 52-week low"].iloc[-1]
    assert not core.strategy_signal(x, 6).iloc[-1]


def test_needs_to_be_near_the_52_week_high():
    # A 50-day high that is still 30% under the 52-week high.
    closes = np.concatenate([np.linspace(100, 300, 150), np.linspace(300, 190, 110),
                             np.full(60, 190.0), [210.0]])
    x = _with_breadth(_series_frame(closes), 0.8)
    m = core.strategy_condition_matrix(x, 6)
    assert m["Fresh 50-day-high breakout"].iloc[-1]
    assert not m["Within 15% of 52-week high"].iloc[-1]


def test_atr_floor():
    quiet = _with_breadth(_series_frame(_leader_breaking_out().close, spread=0.005), 0.8)
    m = core.strategy_condition_matrix(quiet, 6)
    assert not m["ATR >= 2.8% of price"].iloc[-1]
    assert not core.strategy_signal(quiet, 6).iloc[-1]


def test_initial_stop_is_three_atr_below_the_close():
    x = _leader_breaking_out()
    feats = core.strategy6_features(x)
    expected = x.close.iloc[-1] - 3 * feats.s6_atr.iloc[-1]
    assert core.s6_initial_stop(x) == pytest.approx(expected)


def _bars(rows):
    index = pd.bdate_range(start="2026-01-05", periods=len(rows))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)


def test_exit_initial_stop_fills_at_stop_or_gap_open():
    bars = _bars([(100, 101, 99, 100), (99, 100, 88, 90)])
    assert core.s6_exit(bars, 100.0, 89.0) == ("STOP", 89.0)
    gap = _bars([(100, 101, 99, 100), (85, 86, 84, 85)])
    assert core.s6_exit(gap, 100.0, 89.0) == ("STOP", 85.0)


def test_exit_trails_20_percent_below_the_highest_close():
    bars = _bars([(100, 101, 99, 100), (140, 151, 139, 150), (135, 136, 125, 130),
                  (121, 122, 118, 119)])
    # 130 is 13% off the 150 peak - held. 119 is 20.7% off - out at the close.
    assert core.s6_exit(bars, 100.0, 89.0) == ("TRAIL_STOP", 119.0)
    held = _bars([(100, 101, 99, 100), (140, 151, 139, 150), (135, 136, 125, 130)])
    assert core.s6_exit(held, 100.0, 89.0) == ("ACTIVE", None)


def test_attach_market_breadth_joins_by_date_and_carries_forward_only():
    idx = pd.bdate_range(end="2026-06-30", periods=5)
    x = pd.DataFrame({"close": range(5)}, index=idx)
    breadth = pd.Series([0.2, 0.4, 0.6], index=idx[1:4])
    out = core.attach_market_breadth(x, breadth)
    col = out[core.S6_BREADTH_COLUMN]
    assert np.isnan(col.iloc[0])                     # before the first reading
    assert col.iloc[1:4].tolist() == [0.2, 0.4, 0.6]
    assert col.iloc[4] == 0.6                        # a live bar takes the latest reading


def test_scanner_offers_exactly_three_strategies():
    assert len(core.IMPLEMENTED_STRATEGIES) <= 3
    assert 6 in core.IMPLEMENTED_STRATEGIES
    assert not set(core.IMPLEMENTED_STRATEGIES) & set(core.RETIRED_STRATEGIES)
    assert core.S6_LABEL in core.FORWARD_TRACKED_STRATEGIES
    assert core.S6_LABEL in core.TRAILING_EXIT_STRATEGIES
