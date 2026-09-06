"""Regression tests for the GTF research engine.

The audit that motivated this work was about look-ahead, so the tests that
matter most are the truncation tests: a value computed on a truncated frame
must equal the value computed on the full frame at the truncation point.
"""
import numpy as np
import pandas as pd
import pytest

import gtfcore as G


def frame(rows):
    o, h, l, c = map(np.array, zip(*rows))
    return o.astype(float), h.astype(float), l.astype(float), c.astype(float)


# ------------------------------------------------------------------ A1

def test_exciting_is_body_over_half_the_range():
    #                o     h     l     c
    o, h, l, c = frame([
        (10, 12, 10, 11.5),   # body 1.5 / range 2.0 = 0.75 -> exciting
        (10, 12, 10, 11.0),   # body 1.0 / range 2.0 = 0.50 -> NOT exciting (strict >)
        (10, 12, 10, 10.5),   # body 0.5 / range 2.0 = 0.25 -> base
        (10, 10, 10, 10),     # zero range -> base
    ])
    exciting, green = G.classify(o, h, l, c)
    assert list(exciting) == [True, False, False, False]
    assert list(green) == [True, True, True, True]


# ------------------------------------------------------------------ A2/A3

DBR = [
    # drop (exciting red leg-in)
    (110, 111, 100, 101),
    # two base candles
    (101, 103, 99, 102),
    (102, 104, 98, 101),
    # rally (exciting green leg-out)
    (103, 118, 102, 117),
    (117, 130, 116, 129),
]


def test_dbr_zone_marking():
    o, h, l, c = frame(DBR)
    z = G.find_zones(o, h, l, c, kind="demand")
    assert len(z) == 1
    zz = z[0]
    assert zz.n_base == 2
    assert zz.legout_n == 2
    # proximal = highest body of all base candles = max(102, 102) = 102
    assert zz.proximal == pytest.approx(102.0)
    # distal = lowest wick of all base candles = min(99, 98) = 98
    assert zz.distal == pytest.approx(98.0)


def test_supply_marking_mirrors_demand():
    rows = [(100, 111, 99, 110), (109, 111, 107, 108), (108, 112, 106, 107),
            (107, 108, 92, 93), (93, 94, 80, 81)]
    o, h, l, c = frame(rows)
    z = G.find_zones(o, h, l, c, kind="supply")
    assert len(z) == 1
    # proximal = lowest body of all base candles = min(108, 107) = 107
    assert z[0].proximal == pytest.approx(107.0)
    # distal = highest wick of all base candles = max(111, 112) = 112
    assert z[0].distal == pytest.approx(112.0)


def test_leg_out_colour_decides_demand_or_supply():
    o, h, l, c = frame(DBR)
    assert len(G.find_zones(o, h, l, c, kind="demand")) == 1
    assert len(G.find_zones(o, h, l, c, kind="supply")) == 0


# ------------------------------------------------------------------ A6

def test_closing_concept_requires_close_above_leg_in_high():
    o, h, l, c = frame(DBR)          # leg-in high = 111, leg-out closes 117
    assert G.find_zones(o, h, l, c, kind="demand")[0].closing_ok is True

    weak = list(DBR)
    weak[3] = (103, 112, 102, 110.5)  # pokes above 111 but closes below it
    weak[4] = (110.5, 111, 110, 110.6)  # base, so the leg-out run is one candle
    o, h, l, c = frame(weak)
    z = G.find_zones(o, h, l, c, kind="demand")
    assert z and z[0].closing_ok is False


# ------------------------------------------------------------------ A4

def test_freshness_counts_completed_excursions_only():
    rows = list(DBR) + [
        (129, 130, 120, 121),   # coming back down
        (121, 122, 101, 102),   # touches proximal 102 -> excursion opens
        (102, 112, 101, 111),   # leaves the zone -> one completed test
        (111, 112, 100, 101),   # touches again -> excursion open at the end
    ]
    o, h, l, c = frame(rows)
    z = G.find_zones(o, h, l, c, kind="demand")[0]
    n, inside = G.zone_tests(z, h, l, c, upto=len(c) - 1)
    assert n == 1 and inside is True
    # scored while the second excursion is still open: tested once
    assert z.score(n) == pytest.approx(1.5 + 2.0 + 2.0)


def test_trade_score_table():
    o, h, l, c = frame(DBR)
    z = G.find_zones(o, h, l, c, kind="demand")[0]
    assert z.score(0) == pytest.approx(7.0)    # fresh 3 + two leg-outs 2 + 2 bases 2
    assert z.score(1) == pytest.approx(5.5)
    assert z.score(2) == pytest.approx(4.0)


def test_many_base_candles_score_zero_for_time_at_base():
    rows = [(110, 111, 100, 101)] + [(101, 103, 99, 102)] * 6 + [(103, 118, 102, 117)]
    o, h, l, c = frame(rows)
    z = G.find_zones(o, h, l, c, kind="demand")[0]
    assert z.n_base == 6
    assert z.score(0) == pytest.approx(3.0 + 1.0 + 0.0)


# ------------------------------------------------------------------ A7

def test_trend_is_sma50_against_seven_candles_back():
    x = np.arange(100, dtype=float)
    assert G.trend_slope(x, 6)[50] == pytest.approx(6.0)
    assert list(G.trend_state(x, 6)[10:15]) == [1, 1, 1, 1, 1]
    assert list(G.trend_state(-x, 6)[10:15]) == [-1, -1, -1, -1, -1]
    flat = np.full(100, 42.0)
    assert list(G.trend_state(flat, 6)[10:15]) == [0, 0, 0, 0, 0]


# ------------------------------------------------------------------ point in time

def _daily(n=400, seed=7):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
    o = c * (1 + rng.normal(0, 0.004, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n)))
    idx = pd.bdate_range("2021-01-04", periods=n)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": rng.integers(1e5, 1e6, n)}, index=idx)


@pytest.mark.parametrize("freq", ["W", "M"])
def test_aggregation_is_point_in_time(freq):
    """A completed higher-timeframe bar must not change when later data arrives.

    This is the exact defect the audit found in _monthly_asof(): resampling the
    whole frame let an early bar carry its own period's eventual high and close.
    """
    df = _daily()
    full, _, full_last = G.aggregate(df, freq)
    for cut in (137, 201, 288, 355):
        part, _, part_last = G.aggregate(df.iloc[:cut + 1], freq)
        # bars whose period had closed by `cut` must be identical
        done = np.sum(full_last < cut)
        assert done > 0
        for k in range(done):
            for col in ("open", "high", "low", "close", "volume"):
                assert full[col].iloc[k] == pytest.approx(part[col].iloc[k]), (freq, cut, k, col)


def test_zone_detection_is_point_in_time():
    df = _daily()
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy(); c = df["close"].to_numpy()
    full = G.find_zones(o, h, l, c, kind="demand")
    for cut in (150, 250, 330):
        part = G.find_zones(o[:cut], h[:cut], l[:cut], c[:cut], kind="demand")
        # every zone whose leg-out run finished before the cut must match exactly
        settled = [z for z in full if z.legout_start + z.legout_n < cut]
        by_base = {(z.base_lo, z.base_hi): z for z in part}
        assert settled
        for z in settled:
            p = by_base.get((z.base_lo, z.base_hi))
            assert p is not None, (cut, z.base_lo)
            assert p.proximal == pytest.approx(z.proximal)
            assert p.distal == pytest.approx(z.distal)
            assert p.legout_n == z.legout_n
            assert p.n_base == z.n_base


def test_indicators_are_point_in_time():
    df = _daily()
    c = df["close"].to_numpy(); h = df["high"].to_numpy(); l = df["low"].to_numpy()
    for fn, args in ((G.sma, (50,)), (G.ema, (200,)), (G.rsi, (14,))):
        full = fn(c, *args)
        for cut in (250, 320, 390):
            assert fn(c[:cut], *args)[cut - 1] == pytest.approx(full[cut - 1], nan_ok=True)
    full = G.atr(h, l, c, 14)
    for cut in (250, 320, 390):
        assert G.atr(h[:cut], l[:cut], c[:cut], 14)[cut - 1] == pytest.approx(full[cut - 1], nan_ok=True)


def test_rsi_is_100_not_nan_when_there_is_no_average_loss():
    """The production engine returns NaN here, which reads False through every
    'RSI >= 50' gate at exactly the strongest momentum there is."""
    x = np.arange(1, 60, dtype=float)
    assert G.rsi(x, 14)[-1] == pytest.approx(100.0)


# ------------------------------------------------------------------ entry-bar ordering

def test_no_target_can_be_recorded_on_the_entry_bar():
    """Within the bar that filled us, the order of the low and the high is
    unknowable. Recording a target hit there is how a backtest turns a crash
    into a win. The stop is allowed on bar 0; the target is not."""
    import build_events as B
    n = 400
    idx = pd.bdate_range("2021-01-04", periods=n)
    o = np.full(n, 100.0); h = np.full(n, 101.0)
    l = np.full(n, 99.0); c = np.full(n, 100.0)
    # a clean DBR at bars 100-103, then a violent flush into it at bar 140
    o[100], h[100], l[100], c[100] = 110, 111, 100, 101
    o[101], h[101], l[101], c[101] = 101, 103, 99, 102
    o[102], h[102], l[102], c[102] = 103, 118, 102, 117
    o[103], h[103], l[103], c[103] = 117, 130, 116, 129
    for k in range(104, 140):
        o[k], h[k], l[k], c[k] = 129, 130, 128, 129
    # bar 140: opens at 129, crashes to the proximal (102) and closes at 128
    o[140], h[140], l[140], c[140] = 129, 129.5, 101.0, 128.0
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                       "volume": np.full(n, 1e6)}, index=idx)
    rows = B.events_for_symbol(df, "TEST", min_bars=300)
    hit = [r for r in rows if r["bar"] == 140]
    assert hit, "the flush into the zone should produce an arrival"
    r = hit[0]
    for col in [k for k in r if k.endswith("R_bar") or k.endswith("pct_bar")]:
        assert r[col] != 0, f"{col} was recorded on the entry bar"
