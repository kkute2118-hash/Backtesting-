"""The Oracle 4h trend paper book: breakout -> resting limit -> fill -> stop."""

import numpy as np
import pandas as pd

from app.tasks import trend_paper as tp


def _frames():
    # 400 days of a steady uptrend, then a flat 4h range, then a breakout
    idx15 = pd.date_range("2025-01-01", periods=400 * 96, freq="15min", tz="UTC")
    base = np.linspace(100, 200, len(idx15))
    flat = len(idx15) - 30 * 96
    base[flat:] = 200.0
    m15 = pd.DataFrame({"open": base, "high": base + 0.5, "low": base - 0.5, "close": base}, index=idx15)
    # breakout bar: a 4h block closing well above the range
    b = len(idx15) - 5 * 96
    m15.iloc[b:b + 16, :] = [[210, 211, 209, 210]] * 16
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    return m15, m15.resample("4h").agg(agg), m15.resample("1D").agg(agg), b


def test_breakout_rests_a_limit_then_fills_then_stops():
    m15, h4, d1, b = _frames()
    ind = tp.indicators(d1, h4)
    st = {"last15": str(m15.index[b - 1]), "status": "flat"}
    events = tp.advance(st, ind, m15.iloc[:b + 16], "BTCUSDT")
    assert st["status"] == "pending" and abs(st["level"] - 200.5) < 1e-9
    assert any("BREAKOUT" in e for e in events)
    # price comes back to the broken high: filled at the limit
    back = m15.index[b + 16]
    m15.loc[back] = [201, 201, 200, 200.6]
    tp.advance(st, ind, m15.iloc[:b + 17], "BTCUSDT")
    assert st["status"] == "long" and st["entry"] == 200.5
    # then falls through the stop: closed at a loss of a little over 1R
    nxt = m15.index[b + 17]
    m15.loc[nxt] = [199, 199, 150, 151]
    tp.advance(st, ind, m15.iloc[:b + 18], "BTCUSDT")
    assert st["status"] == "flat"
    r = st["closed"][-1]["r"]
    assert -1.2 < r < -1.0
