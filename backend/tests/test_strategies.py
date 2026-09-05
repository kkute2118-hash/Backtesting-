"""Strategy signals and the condition matrix.

The radar's whole premise is that ANDing a strategy's individual conditions
reproduces strategy_signal() exactly. If that ever stops being true the radar
starts reporting blockers for a rule set the scanner does not actually run, so
it is asserted here bar by bar rather than on the latest row only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine import core

STRATEGIES = [1, 2, 3, 4]


@pytest.fixture(scope="module")
def featured(frames):
    return {name: core.features_fast(f"STRAT_{name}", df).replace([np.inf, -np.inf], np.nan)
            for name, df in frames.items()}


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_signal_is_boolean_series_aligned_to_input(featured, strategy):
    for name, f in featured.items():
        sig = core.strategy_signal(f, strategy)
        assert len(sig) == len(f), name
        assert sig.index.equals(f.index), name
        assert sig.dtype == bool, (name, sig.dtype)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_condition_matrix_ands_to_the_signal(featured, strategy):
    """This is the property the Early Warning Radar depends on."""
    for name, f in featured.items():
        matrix = core.strategy_condition_matrix(f, strategy)
        assert matrix, f"{name}/S{strategy} produced no conditions"
        combined = pd.Series(True, index=f.index)
        for series in matrix.values():
            combined &= series.fillna(False)
        expected = core.strategy_signal(f, strategy)
        mismatches = int((combined.astype(bool) != expected).sum())
        assert mismatches == 0, (
            f"{name}/S{strategy}: {mismatches} bar(s) disagree between the "
            "condition matrix and strategy_signal()"
        )


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_signal_needs_every_rule(featured, strategy):
    """A stock never qualifies on one attractive condition — all must pass."""
    f = featured["TRENDUP"]
    matrix = core.strategy_condition_matrix(f, strategy)
    signal = core.strategy_signal(f, strategy)
    for name, series in matrix.items():
        failing = ~series.fillna(False)
        assert not (signal & failing).any(), (
            f"S{strategy} produced a signal on a bar where '{name}' failed"
        )


def test_nan_features_never_qualify():
    """Missing long-term indicators must evaluate False, not raise or pass."""
    index = pd.bdate_range(end="2026-01-01", periods=300)
    empty = pd.DataFrame({c: np.nan for c in core.CUSTOM_DSL_COLUMNS}, index=index)
    for strategy in STRATEGIES:
        assert not core.strategy_signal(empty, strategy).any()


def test_custom_dsl_rejects_unknown_columns():
    conditions, errors = core.parse_custom_strategy("bogus > 1")
    assert not conditions
    assert errors and "unknown column" in errors[0].lower()


def test_custom_dsl_never_evaluates_arbitrary_text():
    """The DSL is whitelist-only. Anything that looks like code is a parse
    error, not something the engine attempts to run."""
    conditions, errors = core.parse_custom_strategy("__import__('os').system('id') > 1")
    assert not conditions and errors


def test_custom_dsl_matches_a_hand_written_predicate(featured):
    f = featured["TRENDUP"]
    conditions, errors = core.parse_custom_strategy("rsi14 > 55\nclose > 1.02 * ema20")
    assert not errors
    produced = core.custom_strategy_signal(f, conditions)
    expected = ((f.rsi14 > 55).fillna(False) & (f.close > 1.02 * f.ema20).fillna(False))
    pd.testing.assert_series_equal(produced, expected, check_names=False)
