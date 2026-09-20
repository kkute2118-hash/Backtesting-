"""The forward-book filter: the three conditions that survived testing.

Guards two things that are easy to break silently. The strategy-label
exemption is one: S4 is labelled "S4_SEPA" in scan output, so a check written
against "S4" alone never fires and the filter looks like it is working while
one of its rules is dead. The other is the direction of each band - both CB
purity and turnover reject on BOTH sides, and a one-sided comparison would
pass every test that only supplies low values.

Reference: research/trader_methodology/FINDINGS_RANKER.md
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine import trader_layer as tl


def frame(n=300, price=200.0, vol=7.0e6, drift=0.0015, seed=11, tower_at=None):
    """A synthetic history with controllable turnover and an optional tower."""
    rng = np.random.default_rng(seed)
    close = pd.Series(price * np.cumprod(1 + rng.normal(drift, 0.02, n)))
    open_ = close.shift(1).fillna(price)
    high = pd.concat([open_, close], axis=1).max(axis=1) * 1.01
    low = pd.concat([open_, close], axis=1).min(axis=1) * 0.99
    v = pd.Series(np.full(n, float(vol)))
    if tower_at is not None:
        v.iloc[tower_at] = vol * 12          # one isolated bar, no cluster
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": v})


def test_turnover_band_rejects_both_ends():
    """A floor alone flips sign between years; the band is what held."""
    low = tl.forward_selection_verdict(frame(vol=3.0e5), "S1")
    high = tl.forward_selection_verdict(frame(vol=8.0e7), "S1")
    assert low[0] is False and "turnover" in low[1]
    assert high[0] is False and "turnover" in high[1]
    assert low[2]["avg_turnover_20"] < tl.FORWARD_FILTER_PARAMS["TURNOVER_MIN_CR"]
    assert high[2]["avg_turnover_20"] > tl.FORWARD_FILTER_PARAMS["TURNOVER_MAX_CR"]


def test_cb_purity_is_a_band_not_a_floor():
    """Above 0.75 the measured return turned sharply negative, so the top
    of the band must reject as firmly as the bottom."""
    p = tl.FORWARD_FILTER_PARAMS
    assert p["CB_MIN"] > 0.0 and p["CB_MAX"] < 1.0, \
        "CB purity must be bounded on both sides"
    ok, why, m = tl.forward_selection_verdict(
        frame(), "S1", {"CB_MIN": 0.95, "CB_MAX": 1.0})
    assert ok is False and "CB purity" in why


@pytest.mark.parametrize("strategy,expected", [
    ("S1", False), ("S2", False), ("S3", False),
    ("S5_POCKETPIVOT", False),
    ("S4", True),            # historical label
    ("S4_SEPA", True),       # the label the engine actually emits
])
def test_single_tower_rejects_except_for_s4(strategy, expected):
    """not-a-tower is worth +0.83 on S1 and -3.94 on S4, so S4 is exempt.

    Both spellings must be exempt: matching only "S4" would silently never
    fire, because scan output and forward tests say "S4_SEPA".
    """
    f = frame(tower_at=-4)
    assert tl.volume_cluster(f.volume, len(f) - 11, len(f) - 1)["single_tower"]
    # Widen the other two bands so this test isolates the tower rule. With the
    # live bands a synthetic frame can reject on CB purity first and the test
    # would pass for the wrong reason - green while the exemption is dead.
    wide = {"CB_MIN": 0.0, "CB_MAX": 1.0,
            "TURNOVER_MIN_CR": 0.0, "TURNOVER_MAX_CR": 1e9}
    ok, why, _ = tl.forward_selection_verdict(f, strategy, wide)
    assert ok is expected, f"{strategy}: {why}"
    if not expected:
        assert "tower" in why


def test_exempt_set_covers_the_label_the_engine_emits():
    from app.engine import core
    s4 = {s for s in core.FORWARD_TRACKED_STRATEGIES if s.startswith("S4")}
    assert s4, "no S4 strategy in FORWARD_TRACKED_STRATEGIES"
    assert s4 <= tl.TOWER_RULE_EXEMPT, (
        f"engine emits {s4} but the exemption only covers {tl.TOWER_RULE_EXEMPT}")


def test_short_history_fails_closed():
    """A condition we could not evaluate is not one we verified - the same
    stance the existing entry-evidence filter takes on NaN."""
    ok, why, _ = tl.forward_selection_verdict(frame(n=20), "S1")
    assert ok is False and "history" in why


def test_wiring_failure_fails_open():
    """The opposite stance for OUR errors: a broken import must not silently
    empty the forward book, and must leave a trace."""
    from app.engine import core
    core.TRADER_FILTER_LAST_ERROR = ""
    ok, why, _ = core._trader_filter_verdict(object(), "S1")   # not a DataFrame
    assert ok is True and why is None
    assert core.TRADER_FILTER_LAST_ERROR, "a swallowed error left no trace"
