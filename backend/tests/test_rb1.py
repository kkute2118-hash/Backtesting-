"""Rulebook v1: candle classes, delta, no look-ahead, a planted sweep, risk limits."""

import numpy as np
import pandas as pd
import pytest

from app.engine.rb1 import backtest as B
from app.engine.rb1 import candles as K
from app.engine.rb1 import config as C
from app.engine.rb1 import delta as D
from app.engine.rb1 import structure as S
from app.engine.rb1.levels import Level, confluence, value_area


# ---------------------------------------------------------------- candles
@pytest.mark.parametrize("bar, want", [
    ((100, 110, 99.5, 109.5), K.BULL_POWER),     # big body, closes at the top
    ((110, 110.5, 100, 100.5), K.BEAR_POWER),
    ((105, 106, 95, 105.5), K.LPR),              # long lower wick, small body
    ((95, 105, 94, 94.5), K.HPR),                # long upper wick
    ((100, 100.5, 99.8, 100.3), K.NONE),         # small bar, no long wick, below 1 ATR
    ((100, 101, 99, 100.2), K.LPR),              # lower wick 1.0 = 5x body and half the range
])
def test_candle_classes(bar, want):
    assert K.classify(*bar, atr=5.0) == want


def test_rejection_wins_over_power():
    # a red bar with a long upper wick is HPR whatever its colour
    assert K.classify(104, 112, 100, 101, atr=2.0) == K.HPR


# ---------------------------------------------------------------- delta
def test_delta_sign_and_neutral():
    assert D.delta_sign(100, 80) == 1
    assert D.delta_sign(100, 20) == -1
    assert D.delta_sign(100, 52) == 0                 # |delta|/volume = 0.04 < 0.10
    assert D.delta_sign(100, np.nan) is None          # gold / forex: no taker volume


def test_bearish_absorption():
    o = np.array([100, 103.0]); h = np.array([104, 103.5]); l = np.array([99.5, 98.0]); c = np.array([102.5, 98.5])
    v = np.array([100.0, 100.0]); tb = np.array([70.0, 30.0])     # buying into resistance, then selling
    cls = np.array([K.HPR, K.BEAR_POWER])
    # bar 0 red? no: o=100 < c=102.5 is green, but it is an HPR, which counts
    assert D.absorption(1, o, h, l, c, v, tb, cls, at_resistance=True, at_support=False) == -1
    assert D.absorption(1, o, h, l, c, v, np.array([np.nan, np.nan]), cls, True, False) is None


# ---------------------------------------------------------------- levels
def test_value_area_covers_70pct_around_the_poc():
    prices = np.r_[np.full(80, 100.0), np.linspace(90, 110, 20)]
    vols = np.ones(100)
    val, vah = value_area(prices, vols)
    assert val <= 100 <= vah and vah - val < 20


def test_confluence_counts_each_kind_once():
    a = Level("PDH", 100, 100, -1, 3)
    near = [a, Level("HTF_OB", 99.9, 100.2, -1, 2), Level("HTF_OB", 99.95, 100.1, -1, 2),
            Level("CDH", 100.05, 100.05, -1, 1), Level("VAH", 105, 105, -1, 2)]
    assert confluence(a, near, merge=0.25) == 3 + 2 + 1


# ---------------------------------------------------------------- engine on synthetic data
def _synthetic(days=20, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-06", periods=days * 288, freq="5min", tz="UTC")
    steps = rng.normal(0, 0.08, len(idx)).cumsum()
    close = 100 + steps + 3 * np.sin(np.arange(len(idx)) / 300)
    op = np.r_[close[0], close[:-1]]
    hi = np.maximum(op, close) + rng.uniform(0, 0.15, len(idx))
    lo = np.minimum(op, close) - rng.uniform(0, 0.15, len(idx))
    vol = rng.uniform(50, 150, len(idx))
    return pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close, "volume": vol,
                         "taker_buy_volume": vol * rng.uniform(0.3, 0.7, len(idx)), "spread": 0.0}, index=idx)


def test_no_lookahead():
    df = _synthetic()
    full = B.run(B.prepare("BTCUSDT", df))
    cut = df.index[len(df) * 2 // 3]
    part = B.run(B.prepare("BTCUSDT", df[df.index < cut]))
    done = lambda tr: [(t["signal_time"], t["setup"], t["side"], round(t["entry"], 9), round(t["stop"], 9))   # noqa: E731
                       for t in tr if pd.Timestamp(t["exit_time"]) < cut - pd.Timedelta("1h")]
    assert done(part) == done(full)
    assert len(full) > 0


def test_planted_pdh_sweep_gives_an_a_sweep_short():
    df = _synthetic(days=6, seed=3)
    # a quiet day, then on day 6 a wick through the previous day's high that closes back below
    P = B.prepare("BTCUSDT", df)
    i = int(np.flatnonzero((pd.DatetimeIndex(P.t, tz="UTC").hour == 10) & (P.day == P.day[-1]))[0])
    pdh, atr = P.pdh[i], P.atr[i]
    P.o[i], P.c[i] = pdh - 0.6 * atr, pdh - 0.5 * atr
    P.h[i], P.l[i] = pdh + 0.3 * atr, pdh - 0.7 * atr
    P.c[i - 1] = pdh - 0.6 * atr
    P.o[i + 1] = P.c[i]                         # the next bar opens where the signal bar closed
    P.cls[i] = K.classify(P.o[i], P.h[i], P.l[i], P.c[i], atr)
    assert P.cls[i] == K.HPR
    levels = [L for L in B.levels_at(P, i) if L.kind in ("PDH", "PDL")]
    levels.append(Level("PDL", P.o[i + 1] - 10 * atr, P.o[i + 1] - 10 * atr, 1, 3))   # the target, room for 2R
    P.piv_l = P.piv_l[:0]                       # no nearer turning point in the way
    P.trend[i] = S.UP                           # against the trend: allowed only at PDH/PDL
    sig = B.find_setup(P, i, levels)
    assert sig and sig["setup"] == "A_SWEEP" and sig["dir"] == -1 and sig["level"] == "PDH"
    assert sig["stop"] == pytest.approx(P.h[i] + C.STOP_BUFFER_ATR * atr)


def test_daily_limits(monkeypatch):
    """After two losses in a day no more trades; size respects 1% risk."""
    df = _synthetic(days=30, seed=7)
    P = B.prepare("BTCUSDT", df)
    tr = pd.DataFrame(B.run(P))
    assert len(tr)
    per_day = tr.assign(day=pd.to_datetime(tr.entry_time).dt.floor("1D")).groupby("day").size()
    assert per_day.max() <= C.MAX_TRADES_PER_DAY
    assert tr.risk_pct.max() <= C.RISK_PER_TRADE_HIGH and tr.risk_pct.min() >= 0.0025
    # a full stop loses about 1R (fees included), never more than a gap allows
    stops = tr[tr.reason == "stop"].r
    assert ((stops > -1.2) & (stops < -0.9)).all()


def test_config_tags():
    names = {n for n, _, _ in C.tagged()}
    assert {"MIN_RR", "POWER_BODY_PCT", "TRADING_WINDOW_UTC"} <= names
