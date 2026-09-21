"""DNA, liquidity and stop quality - the three readings shown on every row.

Marking gates nothing, which makes it the kind of code that can rot without
anything failing. These tests guard the four things that would be wrong and
invisible:

  * the 20-day average must EXCLUDE the bar it is compared against, or a big
    day sits inside its own benchmark and reports itself smaller than it is -
    and the chart, which excludes it, would then disagree with the table;
  * a DNA leg runs to the HIGHEST close before the next swing low, not to the
    first minor high after the low. Taking the first high chops one real move
    into its steps and reports a stock that moves 18% at a time as a 6% stock;
  * "stop inside the demand zone" is his one outright refusal here, so it has
    to fire when the stop is above the pivot and not when it is below;
  * nothing may raise. A marking that throws must cost a candidate nothing,
    because it decides nothing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.engine import trader_layer as tl


def frame(close, volume=None):
    close = pd.Series([float(x) for x in close])
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.concat([open_, close], axis=1).max(axis=1) * 1.005
    low = pd.concat([open_, close], axis=1).min(axis=1) * 0.995
    vol = pd.Series(np.full(len(close), 1.0e6) if volume is None
                    else [float(v) for v in volume])
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": vol})


def test_the_average_excludes_the_day_it_is_compared_against():
    # 60 flat days, then one day on five times the volume. The spike must read
    # 5.00, not the ~4.2 you get when the big day is inside its own average.
    vol = [1.0e6] * 60 + [5.0e6]
    f = frame([100.0] * 61, vol)
    liq = tl.liquidity_marking(f["close"], f["volume"])
    assert liq["avg_turnover_20"] == round(100 * 1.0e6 / 1e7, 1)
    assert abs(liq["turnover_spike"] - 5.0) < 0.01
    assert "flooded" in liq["verdict"]


def test_a_flat_average_is_called_out_as_one_day_not_a_trend():
    f = frame([100.0] * 61, [1.0e6] * 60 + [2.5e6])
    liq = tl.liquidity_marking(f["close"], f["volume"])
    assert liq["turnover_drift_pct"] is not None
    assert liq["turnover_drift_pct"] <= 0
    assert "one day, not a trend" in liq["verdict"]


def test_a_thin_day_says_the_move_has_no_money_behind_it():
    f = frame([100.0] * 61, [1.0e6] * 60 + [0.2e6])
    assert "no money behind it" in tl.liquidity_marking(f["close"], f["volume"])["verdict"]


def _sawtooth(legs, leg_len=20, start=100.0):
    """Repeated up-legs of a given size, each followed by a shallow pullback."""
    out = [start]
    for gain in legs:
        step = (1 + gain / 100.0) ** (1 / leg_len)
        for _ in range(leg_len):
            out.append(out[-1] * step)
        for _ in range(8):                      # give back a third of the leg
            out.append(out[-1] * (1 - gain / 300.0 / 8))
    return out


def test_a_leg_is_measured_to_its_high_not_to_the_first_wobble():
    # Every leg is 20%. Read to the first minor high the answer would be a few
    # percent; read to the leg's own high it is close to 20.
    f = frame(_sawtooth([20.0] * 8))
    d = tl.dna(f["close"])
    assert d["legs"] >= 4
    assert 12.0 <= d["dna_move"] <= 30.0, d


def test_a_quiet_stock_and_a_wild_one_do_not_get_the_same_dna():
    quiet = tl.dna(frame(_sawtooth([5.0] * 10))["close"])
    wild = tl.dna(frame(_sawtooth([30.0] * 10))["close"])
    assert quiet["dna_move"] < wild["dna_move"]
    assert quiet["dna_candle"] < wild["dna_candle"]


def test_dna_returns_nothing_rather_than_a_guess_on_a_short_history():
    d = tl.dna(pd.Series([100.0, 101.0, 102.0]))
    assert d["dna_candle"] is None and d["dna_move"] is None


def test_a_stop_above_the_pivot_is_flagged_as_inside_the_demand_zone():
    f = frame(_sawtooth([15.0] * 6))
    entry = float(f["close"].iloc[-1])
    loose = tl.stop_marking(f, entry, entry * 0.999, 15.0)   # barely below entry
    wide = tl.stop_marking(f, entry, entry * 0.80, 15.0)     # far below any pivot
    if loose["pivot_low"] is not None:
        assert loose["inside_demand_zone"] is True
        assert "INSIDE the demand zone" in loose["verdict"]
    if wide["pivot_low"] is not None:
        assert wide["inside_demand_zone"] is False


def test_a_stop_wider_than_the_whole_typical_move_says_so():
    f = frame(_sawtooth([6.0] * 8))
    entry = float(f["close"].iloc[-1])
    out = tl.stop_marking(f, entry, entry * 0.90, 6.0)
    assert out["sl_vs_dna"] is not None and out["sl_vs_dna"] >= 1.0
    assert "does not clear the risk" in out["verdict"]


def test_a_proportionate_stop_is_stated_as_a_fraction_without_a_verdict():
    f = frame(_sawtooth([20.0] * 8))
    entry = float(f["close"].iloc[-1])
    out = tl.stop_marking(f, entry, entry * 0.97, 20.0)
    assert out["sl_vs_dna"] < 1.0
    assert "does not clear the risk" not in out["verdict"]
    assert "typical move" in out["verdict"]


def test_marking_is_complete_and_never_raises_on_a_short_frame():
    keys = set(tl.marking(frame(_sawtooth([10.0] * 8)), 100.0, 93.0))
    short = tl.marking(frame([100.0] * 10), 100.0, 93.0)
    assert set(short) == keys          # same shape, all None
    assert short["dna_move"] is None
    assert tl.marking(None, 100.0, 93.0)["sl_verdict"] == "not evaluated"


def test_marking_without_an_entry_still_reports_dna_and_liquidity():
    m = tl.marking(frame(_sawtooth([12.0] * 8)))
    assert m["dna_move"] is not None
    assert m["avg_turnover_20"] is not None
    assert m["sl_pct"] is None
