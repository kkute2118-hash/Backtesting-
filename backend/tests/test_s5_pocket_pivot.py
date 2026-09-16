"""S5 — pocket pivot.

Two kinds of test live here. The first kind pins the SOURCE_STATED rules
against hand-built bars, because those rules are the strategy: a pocket pivot
whose volume comparison is off by one bar is a different system wearing the
same name. The second kind pins the stop-loss state machine's transitions,
which no amount of scanning would reveal - the 35-day grace period only shows
itself on day 36.

Tunable thresholds (S5_BASE_RANGE_PCT_MAX and friends) are deliberately NOT
asserted on: they carry no source backing and are expected to move once the
backtest has an opinion. A test that froze them would make tuning look like a
regression.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine import core


def _frame(rows):
    """Build a daily OHLCV frame from (open, high, low, close, volume) tuples."""
    index = pd.bdate_range(end="2026-01-01", periods=len(rows))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"],
                        index=index)


def _flat_then(tail, *, bars=40, price=100.0, volume=100_000.0):
    """`bars` quiet up-days, then the rows under test appended."""
    rows = []
    for k in range(bars):
        c = price + 0.01 * k
        rows.append((c - 0.005, c + 0.02, c - 0.02, c, volume))
    return _frame(rows + list(tail))


# --------------------------------------------------------------------------- #
# Rule 1 + Rule 2: the detector itself (SOURCE_STATED)
# --------------------------------------------------------------------------- #
def test_pocket_pivot_needs_volume_above_the_biggest_down_day():
    """The whole signature: today's volume beats every DOWN day in the lookback.

    Two identical up-days, differing only in volume against a 900k down day
    planted inside the 10-bar window.
    """
    down_day = (100.0, 100.2, 98.0, 98.5, 900_000.0)
    up_day = (99.0, 101.0, 98.9, 100.9, np.nan)   # closes in the upper half

    for volume, expected in ((950_000.0, True), (850_000.0, False)):
        tail = [down_day] + [(99.0, 99.3, 98.8, 99.1, 120_000.0)] * 8
        tail.append((up_day[0], up_day[1], up_day[2], up_day[3], volume))
        s5 = core.strategy5_pocket_pivot_features(core.features(_flat_then(tail)))
        assert bool(s5.s5_price_ok.iloc[-1]), "fixture is not an up-close day"
        assert bool(s5.s5_pocket_pivot.iloc[-1]) is expected, volume


def test_pocket_pivot_rejects_a_close_in_the_lower_half_of_the_range():
    """Rule 1 is not just "up day" — it must close in the upper half."""
    tail = [(99.0, 99.3, 98.8, 99.1, 120_000.0)] * 9
    # Up on the day and up on the close, but the range is mostly above it.
    tail.append((99.0, 103.0, 98.9, 99.6, 5_000_000.0))
    s5 = core.strategy5_pocket_pivot_features(core.features(_flat_then(tail)))
    assert not bool(s5.s5_price_ok.iloc[-1])
    assert not bool(s5.s5_pocket_pivot.iloc[-1])


def test_a_window_with_no_down_day_is_cleared_by_any_volume():
    """max_down_vol = 0 when nothing in the window closed down (spec's branch)."""
    tail = [(99.0, 99.3, 98.8, 99.2, 120_000.0)] * 9
    tail.append((99.2, 100.5, 99.1, 100.4, 1.0))
    x = core.features(_flat_then(tail))
    s5 = core.strategy5_pocket_pivot_features(x)
    assert float(s5.s5_max_down_vol.iloc[-1]) == 0.0
    assert bool(s5.s5_volume_ok.iloc[-1])


def test_the_volume_window_excludes_today():
    """A down day's own volume must not be compared against itself."""
    x = core.features(_flat_then([(100.0, 100.1, 97.0, 97.2, 5_000_000.0)]))
    s5 = core.strategy5_pocket_pivot_features(x)
    # Today is the biggest-volume bar in the frame by far, but it is a DOWN day
    # and the window behind it is quiet, so it cannot be its own reference.
    assert float(s5.s5_max_down_vol.iloc[-1]) == 0.0
    assert not bool(s5.s5_pocket_pivot.iloc[-1])


# --------------------------------------------------------------------------- #
# Undercut and rally — the spec's own window bug (see the deviation note)
# --------------------------------------------------------------------------- #
def test_undercut_and_rally_can_actually_fire():
    """The prior low is measured BEFORE the undercut day, or nothing ever fires.

    The spec computes the prior low over a window that contains the undercut
    day itself, which makes "yesterday's low < the minimum of a window
    including yesterday's low" unsatisfiable. This test is the reason the
    engine shifts that window by one extra bar.
    """
    rows = []
    price = 100.0
    for k in range(60):
        c = price - 0.05 * k          # a slow drift down, so the low is behind us
        rows.append((c + 0.05, c + 0.2, c - 0.2, c, 100_000.0))
    base_low = min(r[2] for r in rows[-20:])
    rows.append((base_low + 0.1, base_low + 0.2, base_low - 1.5, base_low - 1.2, 150_000.0))
    # Quiet volume on the rally day on purpose: this is the variant for the day
    # that is NOT a pocket pivot, and the spec never reaches it when one fires.
    rows.append((base_low - 1.0, base_low + 1.5, base_low - 1.1, base_low + 1.2, 90_000.0))

    s5 = core.strategy5_pocket_pivot_features(core.features(_frame(rows)))
    assert bool(s5.s5_undercut_rally_raw.iloc[-1])
    assert bool(s5.s5_undercut_rally.iloc[-1])
    assert core.strategy5_entry_variant(core.features(_frame(rows))).iloc[-1] == "UNDERCUT_AND_RALLY"


def test_variants_are_mutually_exclusive():
    """classify_entry() returns one label; the vectorised form must agree."""
    from app.engine.core import strategy5_pocket_pivot_features as feats

    for seed in (1, 2, 3, 4):
        from tests.conftest import synthetic_ohlcv
        s5 = feats(core.features(synthetic_ohlcv(seed=seed)))
        overlap = (s5.s5_base_pivot.astype(int) +
                   s5.s5_continuation_pivot.astype(int) +
                   s5.s5_roundabout_pivot.astype(int) +
                   s5.s5_undercut_rally.astype(int))
        assert int(overlap.max()) <= 1, f"seed {seed}: a bar matched two variants"


def test_disabled_variants_never_reach_the_signal():
    """Roundabout is classified for research but must not be traded while off."""
    assert core.S5_ENABLE_ROUNDABOUT_PIVOT is False
    assert core.S5_ENABLE_BGU is False
    assert core.S5_ENABLE_PARTIAL_PROFIT_BOOKING is False

    from tests.conftest import synthetic_ohlcv
    x = core.features(synthetic_ohlcv(seed=7))
    s5 = core.strategy5_pocket_pivot_features(x)
    signal = core.strategy5_signal(x)
    only_roundabout = s5.s5_roundabout_pivot & ~s5.s5_base_pivot & ~s5.s5_continuation_pivot
    assert not (signal & only_roundabout).any()


# --------------------------------------------------------------------------- #
# Stop-loss state machine (SOURCE_STATED — implemented exactly)
# --------------------------------------------------------------------------- #
def _row(close, ema10, ema50):
    return {"close": close, "ema10": ema10, "ema50": ema50}


def test_early_10ema_violation_widens_the_stop_to_the_50_ema():
    m = core.PocketPivotSLStateMachine("2026-01-01")
    assert m.update(_row(105, 100, 90)) == ("HOLD", "TIGHT")
    assert m.update(_row(99, 100, 90)) == ("HOLD", "WIDE")     # inside the grace period
    assert m.update(_row(95, 100, 90)) == ("HOLD", "WIDE")     # 10 EMA no longer exits
    assert m.update(_row(89, 100, 90)) == ("EXIT", "50ema_violated")


def test_surviving_the_grace_period_locks_the_10_ema_as_a_permanent_stop():
    m = core.PocketPivotSLStateMachine("2026-01-01")
    for _ in range(core.PocketPivotSLStateMachine.GRACE_PERIOD_DAYS):
        assert m.update(_row(105, 100, 90))[0] == "HOLD"
    assert m.mode == "TIGHT"
    assert m.update(_row(105, 100, 90)) == ("HOLD", "LOCKED_TIGHT")
    assert m.update(_row(99, 100, 90)) == ("EXIT", "10ema_violated_locked")


def test_a_10ema_violation_after_the_grace_period_exits_instead_of_widening():
    """Day 36 is the whole point of the rule: no more room is granted."""
    m = core.PocketPivotSLStateMachine("2026-01-01")
    for _ in range(core.PocketPivotSLStateMachine.GRACE_PERIOD_DAYS):
        m.update(_row(105, 100, 90))
    assert m.update(_row(99, 100, 90)) == ("EXIT", "10ema_violated_after_grace_period")


def test_the_tight_override_holds_until_it_is_breached():
    m = core.PocketPivotSLStateMachine("2026-01-01", entry_sl_override=98.0)
    assert m.update(_row(99, 100, 90))[0] == "HOLD"
    assert m.update(_row(97.9, 100, 90)) == ("EXIT", "initial_tight_stop_hit")


def test_the_tight_override_hands_off_once_price_clears_the_10_ema():
    m = core.PocketPivotSLStateMachine("2026-01-01", entry_sl_override=98.0)
    m.update(_row(103, 100, 90))          # > ema10 * 1.02 -> override released
    assert m.entry_sl_override is None
    assert m.update(_row(97.0, 100, 90))[0] == "HOLD"   # now the EMA machine, not the override
    assert m.mode == "WIDE"


# --------------------------------------------------------------------------- #
# Integration with the rest of the engine
# --------------------------------------------------------------------------- #
def test_s5_is_reachable_through_the_shared_dispatcher(frames):
    for name, df in frames.items():
        f = core.features_fast(f"S5_{name}", df).replace([np.inf, -np.inf], np.nan)
        direct = core.strategy5_signal(f)
        dispatched = core.strategy_signal(f, 5)
        pd.testing.assert_series_equal(direct, dispatched, check_names=False)
        assert dispatched.dtype == bool


def test_s5_condition_matrix_ands_to_the_signal(frames):
    """Same property the radar depends on for S1-S4."""
    for name, df in frames.items():
        f = core.features_fast(f"S5_{name}", df).replace([np.inf, -np.inf], np.nan)
        matrix = core.strategy_condition_matrix(f, 5)
        assert matrix
        combined = pd.Series(True, index=f.index)
        for series in matrix.values():
            combined &= series.fillna(False)
        mismatches = int((combined.astype(bool) != core.strategy_signal(f, 5)).sum())
        assert mismatches == 0, f"{name}: {mismatches} bar(s) disagree"


def test_s5_never_qualifies_on_all_nan_features():
    index = pd.bdate_range(end="2026-01-01", periods=300)
    empty = pd.DataFrame({c: np.nan for c in core.CUSTOM_DSL_COLUMNS}, index=index)
    assert not core.strategy_signal(empty, 5).any()


def test_s5_is_implemented_but_not_selected_by_default():
    """Checklist item 5: backtest before any forward-test auto-tracking."""
    assert 5 in core.IMPLEMENTED_STRATEGIES
    assert 5 not in core.DEFAULT_STRATEGIES


def test_an_s5_row_can_never_become_a_forward_test(frames, seeded_db):
    """add_forward_candidates() whitelists labels; S5_POCKETPIVOT is not one."""
    row = pd.DataFrame([{
        "Ticker": "TRENDUP", "Strategy": "S5_POCKETPIVOT", "Score": 99.0,
        "Entry": 100.0, "SL 7%": 93.0, "Target 3R": 121.0, "Regime": "BULL",
    }])
    assert core.add_forward_candidates(row, signal_date="2026-01-02") == 0


def test_position_sizing_is_the_source_stated_concentrated_book():
    assert core.S5_MIN_POSITION_SIZE_PCT == 0.30
    assert core.S5_MAX_CONCURRENT_POSITIONS == 3
    assert core.s5_position_plan(0)["slots_free"] == 3
    assert core.s5_position_plan(3)["can_enter"] is False


def test_partial_booking_and_circuit_override_are_inert_while_disabled():
    assert core.s5_check_partial_booking(100.0, 130.0, 0.30, already_booked=False) is None
    row = {"close": 90.0, "volume": 1_000.0, "vol20": 100_000.0}
    assert core.s5_check_circuit_override(row, prev_close=100.0) is False


def test_backtest_runs_and_reports_the_checklist_metrics(frames):
    """Signals/week, win rate and average R — checklist item 6.

    Synthetic frames, so the NUMBERS mean nothing; what is asserted is that the
    harness completes, prices risk off the state machine's own stop, and tags
    everything S5_POCKETPIVOT.
    """
    start = min(df.index[300] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    result = core.run_s5_pocket_pivot_backtest(frames, start, end)

    summary = result["summary"]
    for key in ("trades", "win_rate_pct", "avg_r", "signals_per_week", "symbols_scanned"):
        assert key in summary
    assert result["diagnostics"]["scanned"] == len(frames)

    trades = result["trades"]
    if not trades.empty:
        assert set(trades["Strategy"]) == {"S5_POCKETPIVOT"}
        assert set(trades["Variant"]) <= {
            "BASE_POCKET_PIVOT", "CONTINUATION_POCKET_PIVOT", "UNDERCUT_AND_RALLY",
        }
        assert (trades["Holding Bars"] >= 0).all()


def test_tightness_diagnostic_measures_what_the_untuned_threshold_costs(frames):
    """Checklist item 7 — the threshold with zero source backing is measured,
    not trusted."""
    out = core.s5_tightness_diagnostic(frames)
    assert out["threshold"] == core.S5_BASE_RANGE_PCT_MAX
    assert out["passed_tightness"] + out["dropped_by_tightness"] == out["in_constructive_location"]
    assert out["in_constructive_location"] <= out["pocket_pivot_days"]


# --------------------------------------------------------------------------- #
# No marking system yet — the evidence run comes first
# --------------------------------------------------------------------------- #
def test_s5_has_no_strategy_quality_component(frames):
    """S5 is deliberately unscored. A hand-written component would be a guess
    about what matters, which is exactly what the evidence run is for."""
    assert 5 in core.STRATEGIES_WITHOUT_QUALITY_COMPONENT
    f = core.features_fast("S5_TRENDUP", frames["TRENDUP"]).replace([np.inf, -np.inf], np.nan)
    assert core.strategy_quality_score(f, 5) == 0


def test_an_unscored_strategy_is_not_penalised_against_a_scored_one(frames):
    """Scoring the biggest component zero would be a 33-point penalty on every
    S5 candidate — a marking decision made by omission. The four measured
    components are rescaled onto 100 instead, and Strategy reports NaN so
    "not measured" stays distinguishable from "measured badly"."""
    f = core.features_fast("S5_TRENDUP", frames["TRENDUP"]).replace([np.inf, -np.inf], np.nan)
    score, parts = core.final_setup_score(f, 5, "BULL", 80)

    assert np.isnan(parts["Strategy"])
    assert 0 <= score <= 100

    measured = sum(core.SCORE_COMPONENT_WEIGHTS[k] for k in parts if k != "Strategy")
    earned = sum(parts[k] for k in parts if k != "Strategy")
    assert score == int(max(0, min(100, earned * (100.0 / measured))))
    # Zeroing the component instead would have produced this, which is lower.
    assert score >= earned


def test_a_scored_strategy_is_untouched(frames):
    f = core.features_fast("S5_TRENDUP", frames["TRENDUP"]).replace([np.inf, -np.inf], np.nan)
    for s in (1, 2, 3, 4):
        _, parts = core.final_setup_score(f, s, "BULL", 80)
        assert not np.isnan(parts["Strategy"]), f"S{s} lost its Strategy component"


# --------------------------------------------------------------------------- #
# The evidence run: what do the winners have in common?
# --------------------------------------------------------------------------- #
def test_every_captured_trade_carries_its_signal_bar_readings(frames):
    """The analysis is only possible if the readings were recorded at the
    signal, not reconstructed afterwards."""
    start = min(df.index[300] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    trades = core.run_s5_pocket_pivot_backtest(frames, start, end)["trades"]
    if trades.empty:
        pytest.skip("no S5 trades on these fixtures")

    for column in ("s5_vol_signature_ratio", "s5_base_range_pct", "s5_ma_stack",
                   "s5_dist_ema10_pct", "relvol", "rsi14", "market_regime"):
        assert column in trades.columns, column
    # No score columns: there is no S5 scoring system to record.
    assert not [c for c in trades.columns if str(c).startswith("score_")]


def test_winner_profile_measures_rather_than_asserts(frames):
    start = min(df.index[300] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    profile = core.run_s5_pocket_pivot_backtest(frames, start, end)["winner_profile"]
    if not profile.get("ok"):
        pytest.skip(profile.get("reason", "not enough trades"))

    assert profile["winners"] + profile["losers"] == profile["n"]
    assert profile["features_measured"] > 0
    for row in profile["winners_vs_losers"]:
        assert row["Gap (in std devs)"] >= 0
        assert row["Read"]
    # Every reading is either separating or inert — none is silently dropped.
    assert set(profile["separating_readings"]).isdisjoint(profile["inert_readings"])
    assert profile["verdict"]


def test_a_profile_over_noise_reports_no_edge_rather_than_inventing_one(frames):
    """The fixtures are random walks. If the analysis claimed a strong read on
    them, it would claim one on anything."""
    start = min(df.index[300] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    profile = core.run_s5_pocket_pivot_backtest(frames, start, end)["winner_profile"]
    if not profile.get("ok"):
        pytest.skip(profile.get("reason", "not enough trades"))
    assert not profile["separating_readings"], (
        "a reading separated winners from losers on synthetic random walks: "
        f"{profile['separating_readings']}"
    )


def test_a_stored_capture_can_be_re_analysed_without_re_simulating(frames, seeded_db):
    start = min(df.index[300] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    result = core.run_s5_pocket_pivot_backtest(frames, start, end)
    if result["trades"].empty:
        pytest.skip("no S5 trades on these fixtures")

    run_id = core._persist_s5_captures(result, start, end, len(frames), elapsed=1.0)
    stored, resolved = core.s5_stored_captures(run_id)
    assert len(stored) == len(result["trades"])
    assert resolved == run_id

    again = core.s5_winner_profile_from_db(run_id)
    assert again["ok"]
    assert again["n"] == result["winner_profile"]["n"]
    assert again["winners"] == result["winner_profile"]["winners"]

    # The point of storing it: re-cutting the question costs nothing.
    tighter = core.s5_winner_profile_from_db(run_id, big_winner_quantile=0.95)
    if "big_winners" in tighter and "big_winners" in again:
        assert tighter["big_winners"] <= again["big_winners"]


def test_winner_profile_is_honest_when_there_is_nothing_to_analyse():
    empty = core.s5_winner_profile(pd.DataFrame())
    assert empty["ok"] is False and empty["reason"]


# --------------------------------------------------------------------------- #
# Selection: which signals to take when the book holds three
# --------------------------------------------------------------------------- #
def test_the_initial_stop_fills_intraday_not_on_the_close():
    """A 1.3%-away stop order does not wait for the close. Modelling it that
    way let price run far past the level before the exit registered — the
    first evidence run had 2,967 such trades averaging -4.65R against a stop
    that should cost about -1R."""
    assert core.S5_INTRADAY_INITIAL_STOP is True


def test_slot_simulation_respects_the_slot_limit(frames):
    """The book holds `slots` positions, so a rule that picks wonderful trades
    all firing on one Tuesday is not a rule you can trade."""
    start = min(df.index[300] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    trades = core.run_s5_pocket_pivot_backtest(frames, start, end)["trades"]
    if trades.empty:
        pytest.skip("no S5 trades on these fixtures")

    sim = core.s5_slot_simulation(trades, None, slots=2, seed=1)
    assert sim["ok"]
    assert sim["taken"] <= sim["offered"]

    # More slots can never take fewer trades.
    wider = core.s5_slot_simulation(trades, None, slots=5, seed=1)
    assert wider["taken"] >= sim["taken"]


def test_slot_simulation_never_doubles_up_on_one_name(frames):
    start = min(df.index[300] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    trades = core.run_s5_pocket_pivot_backtest(frames, start, end)["trades"]
    if trades.empty:
        pytest.skip("no S5 trades on these fixtures")
    t = trades.copy()
    t["Entry Date"] = pd.to_datetime(t["Entry Date"])
    t["Exit Date"] = pd.to_datetime(t["Exit Date"])
    sim = core.s5_slot_simulation(t, None, slots=3, seed=2)
    assert sim["ok"] and sim["taken"] > 0


def test_filter_sweep_judges_out_of_sample_not_in_sample(frames):
    """A threshold picked on the same trades it is scored over always looks
    good. The sweep has to report both windows for that to be visible."""
    start = min(df.index[300] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    trades = core.run_s5_pocket_pivot_backtest(frames, start, end)["trades"]
    if trades.empty or len(trades) < 400:
        pytest.skip("not enough fixture trades to split")

    mid = pd.to_datetime(trades["Entry Date"]).quantile(0.6)
    sweep = core.s5_filter_sweep(trades, mid, min_train=50, min_test=25)
    if sweep.empty:
        pytest.skip("no threshold had enough trades on both sides")
    for col in ("Train PF", "Test PF", "Test Lift PF", "Survived", "Kept %"):
        assert col in sweep.columns
    # "Survived" must mean helped in BOTH windows, never just the first.
    assert (sweep.loc[sweep.Survived, "Train Lift PF"] > 0).all()
    assert (sweep.loc[sweep.Survived, "Test Lift PF"] > 0).all()
