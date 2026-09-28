"""The page's S6 trigger and "eligible from" must match the engine exactly:
a close above the trigger on or after that date is a fresh S6 breakout, and
nothing else is."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from app.engine import core  # noqa: E402


def _series(seed, n=320):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.02, n)))
    high = close * (1 + rng.uniform(0, 0.02, n))
    low = close * (1 - rng.uniform(0, 0.02, n))
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                         "volume": 1e6}, index=idx)


def _with_next_close(x, price, date=None):
    date = date or x.index[-1] + pd.offsets.BDay(1)
    bar = pd.DataFrame({"open": price, "high": price, "low": price, "close": price,
                        "volume": 1e6}, index=[date])
    return pd.concat([x, bar])


@pytest.mark.parametrize("seed", range(12))
def test_trigger_and_eligibility_match_the_engine(seed):
    import claude_dashboard as cd
    x = _series(seed)
    trigger, last_bo, eligible = cd.s6_next_decision(x, forming_bar=False)
    day = eligible or (x.index[-1] + pd.offsets.BDay(1))
    after = x if eligible is None else x                 # nothing in between: same history
    above = core.strategy6_features(_with_next_close(after, trigger * 1.001, day)).s6_fresh_breakout.iloc[-1]
    below = core.strategy6_features(_with_next_close(after, trigger * 0.999, day)).s6_fresh_breakout.iloc[-1]
    assert bool(above) and not bool(below)
    if eligible is not None:
        early = eligible - pd.Timedelta(days=1)
        assert not core.strategy6_features(_with_next_close(x, trigger * 1.001, early)).s6_fresh_breakout.iloc[-1]


def test_intraday_the_forming_bar_is_not_part_of_the_trigger():
    import claude_dashboard as cd
    x = _series(3)
    live = _with_next_close(x, float(x.high.tail(50).max()) * 1.05)   # today's candle, still forming
    trig_live, _, _ = cd.s6_next_decision(live, forming_bar=True)
    trig_eod, _, _ = cd.s6_next_decision(x, forming_bar=False)
    assert trig_live == pytest.approx(trig_eod)                       # same decision: today's close
