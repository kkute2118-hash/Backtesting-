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


def test_turnover_has_a_floor_but_no_ceiling():
    """The ceiling was measured as HARMFUL on the full store and removed.

    On the 161-symbol fixture ">400 crore" meant index heavyweights, so the
    rule was really "avoid mega-caps". On 3,303 symbols, where 400 crore is an
    ordinary mid-cap, high turnover outperforms in both years. A ceiling must
    never come back without evidence from a broad universe.
    """
    low = tl.forward_selection_verdict(frame(vol=3.0e5), "S1")
    assert low[0] is False and "turnover" in low[1]

    very_high = tl.forward_selection_verdict(
        frame(vol=8.0e7), "S1", {"CB_MIN": 0.0})
    assert very_high[2]["avg_turnover_20"] > 400, "fixture is not high-turnover"
    assert very_high[0] is True, "a very liquid stock must not be rejected"


def test_cb_purity_is_a_floor_with_no_upper_bound():
    """The fixture's upper bound also reversed on the full store.

    There, purity above 0.75 was the BEST bucket (+3.12%), not the worst, so
    the band was fixture noise. The threshold that survives both years on both
    controls is a plain floor at 0.60.
    """
    p = tl.FORWARD_FILTER_PARAMS
    assert p["CB_MIN"] >= 0.60, "0.30 and 0.40 both failed 2025"
    assert p["CB_MAX"] > 1.0, "a CB ceiling was measured as harmful"

    ok, why, _ = tl.forward_selection_verdict(frame(), "S1", {"CB_MIN": 0.95})
    assert ok is False and "CB purity" in why


@pytest.mark.parametrize("strategy", ["S1", "S2", "S3", "S4", "S4_SEPA",
                                      "S5_POCKETPIVOT"])
def test_single_tower_no_longer_rejects_anything(strategy):
    """The tower rule is off: it had no stable edge on the full store.

    The gap is -0.91% in 2025 and +0.08% in 2026 on live-equivalent signals -
    it flips sign - and S3, S4 and S5 all do BETTER on a tower. The earlier
    S4-only exemption was directionally right and far too narrow.
    """
    expected = True
    f = frame(tower_at=-4)
    assert tl.volume_cluster(f.volume, len(f) - 11, len(f) - 1)["single_tower"]
    # Widen the other two bands so this test isolates the tower rule. With the
    # live bands a synthetic frame can reject on CB purity first and the test
    # would pass for the wrong reason - green while the exemption is dead.
    wide = {"CB_MIN": 0.0, "TURNOVER_MIN_CR": 0.0}
    ok, why, _ = tl.forward_selection_verdict(f, strategy, wide)
    assert ok is expected, f"{strategy}: {why}"
    assert not tl.APPLY_TOWER_RULE


def test_exempt_set_covers_the_label_the_engine_emits():
    """Only meaningful while the tower rule is on. Kept because the trap it
    guards is subtle: the engine emits "S4_SEPA", so an exemption written
    against "S4" never fires and the filter looks like it is working."""
    if not tl.APPLY_TOWER_RULE:
        pytest.skip("tower rule is off; nothing to exempt")
    from app.engine import core
    s4 = {s for s in core.FORWARD_TRACKED_STRATEGIES if s.startswith("S4")}
    assert s4 and s4 <= tl.TOWER_RULE_EXEMPT


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
