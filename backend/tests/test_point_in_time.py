"""Point-in-time universe, the replayed entry filter, and the S6 replay."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.engine import core


def _frame(close, volume, n=120, end="2026-06-30"):
    idx = pd.bdate_range(end=end, periods=n)
    c = np.full(n, float(close)) if np.isscalar(close) else np.asarray(close, float)
    v = np.full(n, float(volume)) if np.isscalar(volume) else np.asarray(volume, float)
    return pd.DataFrame({"open": c, "high": c * 1.02, "low": c * 0.98, "close": c, "volume": v}, index=idx)


def test_universe_ranks_by_trailing_turnover_only():
    big = _frame(100, 1_000_000)
    small = _frame(100, 1_000)
    # "riser" is tiny until its last day, when volume explodes. The trailing
    # window is shifted a day, so that last day must not vote it in.
    v = np.full(120, 1_000.0); v[-1] = 1e9
    riser = _frame(100, v)
    e = core.point_in_time_universe({"BIG": big, "SMALL": small, "RISER": riser}, top_n=1)
    last = e.index[-1]
    assert bool(e.at[last, "BIG"]) and not bool(e.at[last, "RISER"]) and not bool(e.at[last, "SMALL"])


def test_universe_needs_history_before_a_stock_is_eligible():
    e = core.point_in_time_universe({"A": _frame(100, 1_000)}, top_n=5)
    assert not e["A"].iloc[: core.PIT_MIN_HISTORY].any()
    assert e["A"].iloc[-1]


def test_replayed_filter_uses_the_signal_day_not_today():
    # Liquid for 100 days, then turnover collapses. A signal while liquid must
    # pass the turnover floor; the same stock judged on its last day must not.
    v = np.r_[np.full(100, 5_000_000.0), np.full(20, 10.0)]
    c = 100 + np.sin(np.arange(120)) * 5          # enough range for ATR >= 4%
    df = _frame(c, v)
    df["high"], df["low"] = df.close * 1.04, df.close * 0.96
    early = core.historical_entry_verdict(5, df, df.index[90])
    late = core.historical_entry_verdict(5, df, df.index[-1])
    assert early[0], early
    assert not late[0] and "turnover" in late[1]


def test_s6_replay_exits_on_its_own_rules():
    idx = pd.bdate_range(end="2026-06-30", periods=330)
    rise = np.linspace(100, 200, 269)
    base = np.full(60, 190.0)
    close = np.r_[rise, base, 215.0]
    x = pd.DataFrame({"open": close, "high": close * 1.03, "low": close * 0.97,
                      "close": close, "volume": 1e6}, index=idx)
    breadth = pd.Series(0.8, index=idx)
    t = core.run_s6_backtest({"LEADER": x}, idx[0], idx[-1], breadth=breadth)
    assert len(t) == 1
    row = t.iloc[0]
    assert row["Exit Reason"] == "OPEN"          # signal on the last bar: nothing to exit on yet
    assert row["Initial SL"] < row["Entry"]


def test_price_gap_guard_finds_split_like_moves_only_inside_the_lookback():
    idx = pd.bdate_range(end="2026-06-30", periods=300)
    c = np.full(300, 100.0)
    c[100:] = 50.0                                   # a 1:1 bonus, 200 bars ago
    df = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1e6}, index=idx)
    gap = core.recent_price_gap(df)
    assert gap is not None and gap[0] == idx[100].date() and gap[1] == -50.0
    assert core.recent_price_gap(df, lookback=150) is None          # older than the window
    calm = df.assign(close=np.linspace(100, 130, 300), open=np.linspace(100, 130, 300))
    assert core.recent_price_gap(calm) is None


def test_replayed_filter_withholds_signals_after_a_gap():
    idx = pd.bdate_range(end="2026-06-30", periods=120)
    c = 100 + np.sin(np.arange(120)) * 5
    c[60:] = c[60:] / 2                              # unadjusted split
    df = pd.DataFrame({"open": c, "high": c * 1.04, "low": c * 0.96, "close": c,
                       "volume": 5_000_000.0}, index=idx)
    ok, why, _ = core.historical_entry_verdict(5, df, idx[-1])
    assert not ok and "price gap" in why
