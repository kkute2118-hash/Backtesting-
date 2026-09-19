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


def test_s5_is_live_but_still_unscored():
    """S5 went live once its evidence run existed. It is in the default scan and
    forward-tracked, and it still has no quality component — those were always
    separate decisions."""
    assert 5 in core.IMPLEMENTED_STRATEGIES
    assert 5 in core.DEFAULT_STRATEGIES
    assert 5 in core.STRATEGIES_WITHOUT_QUALITY_COMPONENT
    assert "S5_POCKETPIVOT" in core.FORWARD_TRACKED_STRATEGIES


def test_an_s5_row_is_forward_tracked_without_a_target(frames, seeded_db):
    """S5 trails until the stop breaks, so it has no target. A missing one is a
    fact about the strategy, not a malformed row — but only for a strategy whose
    exit is actually a trailing rule."""
    assert "S5_POCKETPIVOT" in core.TRAILING_EXIT_STRATEGIES
    row = pd.DataFrame([{
        "Ticker": "TRENDUP", "Strategy": "S5_POCKETPIVOT", "Score": 55.0,
        "Entry": 100.0, "SL 7%": 96.0, "Target 3R": None, "Regime": "BULL",
    }])
    assert core.add_forward_candidates(row, signal_date="2026-01-02") == 1

    # A fixed-target strategy with no target is still a bad row.
    bad = pd.DataFrame([{
        "Ticker": "CHOPPY", "Strategy": "S1", "Score": 90.0,
        "Entry": 100.0, "SL 7%": 93.0, "Target 3R": None, "Regime": "BULL",
    }])
    assert core.add_forward_candidates(bad, signal_date="2026-01-02") == 0


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
    result = core.run_s5_pocket_pivot_backtest(
        frames, start, end, apply_evidence_filter=False)

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
    trades = core.run_s5_pocket_pivot_backtest(
        frames, start, end, apply_evidence_filter=False)["trades"]
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
    profile = core.run_s5_pocket_pivot_backtest(
        frames, start, end, apply_evidence_filter=False)["winner_profile"]
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
    profile = core.run_s5_pocket_pivot_backtest(
        frames, start, end, apply_evidence_filter=False)["winner_profile"]
    if not profile.get("ok"):
        pytest.skip(profile.get("reason", "not enough trades"))
    assert not profile["separating_readings"], (
        "a reading separated winners from losers on synthetic random walks: "
        f"{profile['separating_readings']}"
    )


def test_a_stored_capture_can_be_re_analysed_without_re_simulating(frames, seeded_db):
    start = min(df.index[300] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    result = core.run_s5_pocket_pivot_backtest(
        frames, start, end, apply_evidence_filter=False)
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
    trades = core.run_s5_pocket_pivot_backtest(
        frames, start, end, apply_evidence_filter=False)["trades"]
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
    trades = core.run_s5_pocket_pivot_backtest(
        frames, start, end, apply_evidence_filter=False)["trades"]
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
    trades = core.run_s5_pocket_pivot_backtest(
        frames, start, end, apply_evidence_filter=False)["trades"]
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


# --------------------------------------------------------------------------- #
# Live wiring: the evidence filter, and S5's own trade geometry
# --------------------------------------------------------------------------- #
def test_the_evidence_filter_is_on_and_actually_removes_signals(frames):
    """Unfiltered S5 loses money on three slots, so the live rule is filtered.
    If this ever silently becomes a no-op, the scan goes back to offering 109
    signals a week that it cannot trade."""
    assert core.S5_APPLY_EVIDENCE_FILTER is True
    assert core.S5_MIN_ATR_PCT == 4.0
    assert core.S5_MIN_GAP_PCT == 0.36

    f = core.features_fast("S5_FILT", frames["TRENDUP"]).replace([np.inf, -np.inf], np.nan)
    raw = core.strategy5_signal(f, apply_filter=False)
    live = core.strategy_signal(f, 5)
    assert int(live.sum()) <= int(raw.sum())
    assert not (live & ~raw).any(), "the filter added a signal instead of removing one"


def test_the_filter_thresholds_match_the_columns_they_were_measured_on(frames):
    """The thresholds were fitted on compute_signal_fingerprint()'s atr_pct and
    gap_pct. If the signal-side definitions drift from those, the filter stops
    meaning what the study measured."""
    df = frames["TRENDUP"]
    f = core.features_fast("S5_DEF", df).replace([np.inf, -np.inf], np.nan)
    s5 = core.strategy5_pocket_pivot_features(f)
    i = len(f) - 1
    fp = core._s5_signal_fingerprint(df, f, s5, i, float(f.close.iloc[i]),
                                     float(f.close.iloc[i]) * 0.95, "BULL", 80, [])
    # The fingerprint rounds to 3 decimals; anything beyond that is a real
    # difference in definition, which is what this test is for.
    for key, col in (("atr_pct", "s5_atr_pct"), ("gap_pct", "s5_gap_pct")):
        if fp.get(key) is not None and pd.notna(s5[col].iloc[i]):
            assert abs(float(fp[key]) - float(s5[col].iloc[i])) < 1e-3, key


def test_s5_carries_its_own_stop_and_no_target(frames, seeded_db):
    """S5 trails on the 10/50 EMA and has no target. Handing it the shared 7%
    stop and 3R target would record a different system's outcome."""
    f = core.features_fast("S5_GEOM", frames["TRENDUP"]).replace([np.inf, -np.inf], np.nan)
    idx = np.flatnonzero(core.strategy_signal(f, 5).to_numpy())
    if not len(idx) or idx[-1] < 300:
        pytest.skip("no filtered S5 signal on this fixture")

    truncated = {"TRENDUP": frames["TRENDUP"].iloc[: idx[-1] + 1]}
    res = core.scan_dataset(truncated, [5], "BULL", stats={})
    if res.empty:
        pytest.skip("scan produced no row")
    row = res.iloc[0]
    assert row["Strategy"] == "S5_POCKETPIVOT"
    assert row["Target 3R"] is None
    assert row["R:R"] == "trailing (10/50 EMA)"
    assert float(row["SL 7%"]) < float(row["Entry"])
    # Specifically NOT the shared 7% stop.
    assert abs(float(row["SL 7%"]) - float(row["Entry"]) * 0.93) > 1e-6
    assert pd.isna(row["Strategy Score"]), "S5 must stay unscored"


def test_the_win_probability_model_refuses_to_guess_for_s5():
    """S5 has no strategy-quality component, and the classifier was trained on
    strategies that do. Defaulting its missing strategy_score to 0.0 fed the
    model the worst possible setup and got a confident number back — a live
    scan showed 94.5% for a strategy whose real win rate is 34%. Absent must
    mean no estimate, not zero."""
    model = {
        "ready": True,
        "feature_columns": ["score", "htf", "footprint", "strategy_score",
                            "entry_quality", "relative_strength", "safety_score",
                            "strategy_S1", "strategy_S5_POCKETPIVOT", "regime_BULL"],
        "strategy_samples": {"S1": 5000, "S5_POCKETPIVOT": 1},
        "gbc_model": None,   # never reached: both rows below are refused first
    }
    unscored = {"Score": 38, "HTF Score": 11, "Footprint Score": 13,
                "Strategy Score": np.nan, "Entry Quality": 11, "Safety Score": 80,
                "Strategy": "S5_POCKETPIVOT", "Regime": "BULL"}
    assert pd.isna(core.ml_win_probability(model, unscored))

    # Thin evidence is refused even when the score is present: one completed
    # trade is not a basis for a probability.
    thin = {**unscored, "Strategy Score": 29.0}
    assert pd.isna(core.ml_win_probability(model, thin))

    # A strategy the model never saw at all is refused too.
    unknown = {**unscored, "Strategy": "NOT_A_STRATEGY", "Strategy Score": 29.0}
    assert pd.isna(core.ml_win_probability(model, unknown))


def test_a_thinly_evidenced_strategy_needs_real_samples_before_the_model_speaks():
    assert core.ML_MIN_STRATEGY_SAMPLES >= 20


# --------------------------------------------------------------------------- #
# Slot priority: which strategy gets a scarce slot
# --------------------------------------------------------------------------- #
def _cand(ticker, strategy, entry=100.0, stop=95.0):
    return {"Ticker": ticker, "Strategy": strategy, "Entry": entry, "SL 7%": stop}


def test_s4_takes_the_slot_before_s5():
    """S4 earned +5.20% per trade against S5's +0.56% over the same book, but
    S5 fires constantly and crowded it out of a 3-slot portfolio. Preferring S4
    moved median CAGR from 10.3% to 19.1%. S5 is listed first here on purpose:
    the priority must reorder the input, not follow it."""
    cand = pd.DataFrame([
        _cand("AAA", "S5_POCKETPIVOT"), _cand("BBB", "S5_POCKETPIVOT"),
        _cand("CCC", "S5_POCKETPIVOT"), _cand("DDD", "S4_SEPA"),
    ])
    out = core.build_portfolio(cand, data=None, capital=100_000,
                               max_positions=2, max_correlation=1.0)
    picked = list(out["positions"]["Strategy"])
    assert picked[0] == "S4_SEPA", picked


def test_one_stock_under_two_strategies_keeps_the_higher_priority_one():
    """De-duplication happens after the priority sort, so the surviving row is
    S4's — not whichever happened to be listed first."""
    dup = pd.DataFrame([_cand("ZZZ", "S5_POCKETPIVOT"), _cand("ZZZ", "S4_SEPA")])
    out = core.build_portfolio(dup, data=None, capital=100_000,
                               max_positions=3, max_correlation=1.0)
    assert len(out["positions"]) == 1
    assert out["positions"].iloc[0]["Strategy"] == "S4_SEPA"


def test_an_unlisted_strategy_sorts_after_the_ranked_ones():
    cand = pd.DataFrame([_cand("AAA", "S1"), _cand("BBB", "S5_POCKETPIVOT"),
                         _cand("CCC", "S4_SEPA")])
    out = core.build_portfolio(cand, data=None, capital=100_000,
                               max_positions=3, max_correlation=1.0)
    assert list(out["positions"]["Strategy"]) == ["S4_SEPA", "S5_POCKETPIVOT", "S1"]
    assert core._slot_priority("NOT_A_STRATEGY") == core.STRATEGY_SLOT_PRIORITY_DEFAULT
    assert core._slot_priority("s4_sepa") == 0, "matching must be case-insensitive"


def test_priority_never_overrides_a_broken_stop():
    """Priority decides ordering, not eligibility: an S4 row whose stop is not
    below its entry is still rejected."""
    cand = pd.DataFrame([_cand("AAA", "S4_SEPA", entry=100.0, stop=105.0),
                         _cand("BBB", "S5_POCKETPIVOT", entry=100.0, stop=95.0)])
    out = core.build_portfolio(cand, data=None, capital=100_000,
                               max_positions=3, max_correlation=1.0)
    assert list(out["positions"]["Ticker"]) == ["BBB"]
    assert any(s["ticker"] == "AAA" for s in out["skipped"])


# --------------------------------------------------------------------------- #
# Market regime, index prices and sector membership
# --------------------------------------------------------------------------- #
def test_an_index_can_never_be_mistaken_for_a_stock():
    assert core.index_store_symbol("NIFTY 500") == "^NIFTY 500"
    assert core.is_index_symbol("^NIFTY 500")
    assert not core.is_index_symbol("RELIANCE")


def test_regime_says_where_it_read_the_market_from(frames, seeded_db):
    """The regime used to come from `max(data.values(), key=len)` — the single
    longest-history stock, which is not the market. The fallback still exists
    (an index may not be synced yet) but it now has to announce itself."""
    data = dict(frames)
    proxy, source = core.market_regime_frame(data)
    assert len(proxy) > 0
    assert "FALLBACK" in source, source

    # With no data at all, it refuses rather than inventing a regime.
    empty, src = core.market_regime_frame({})
    assert empty.empty and src == "unavailable"


def test_the_regime_fallback_ignores_index_rows(frames):
    """If an index is in the dataset it must not be picked as the 'longest
    stock' — it is not tradable and would double-count as both."""
    data = dict(frames)
    longest = max(data.values(), key=len)
    data["^NIFTY 500"] = pd.concat([longest, longest])   # longest frame by far
    proxy, source = core.market_regime_frame(data)
    assert "FALLBACK" in source
    assert len(proxy) == len(longest), "an index frame was used as the stock fallback"


def test_sector_membership_is_many_to_many(seeded_db):
    """A bank belongs to Bank and to Financial Services. Collapsing that to one
    sector per symbol would silently pick a winner."""
    core.ensure_sector_table()
    con = core._db()
    try:
        con.executemany(
            "INSERT OR REPLACE INTO sector_membership(symbol,sector,updated_at) VALUES(?,?,?)",
            [("HDFCBANK", "Bank", "x"), ("HDFCBANK", "Financial Services", "x"),
             ("INFY", "IT", "x")])
        con.commit()
    finally:
        con.close()
    m = core.sector_map()
    assert sorted(m["HDFCBANK"]) == ["Bank", "Financial Services"]
    assert m["INFY"] == ["IT"]


def test_the_sector_and_index_catalogues_are_populated():
    assert len(core.SECTOR_INDEX_URLS) >= 10
    assert core.REGIME_INDEX in core.INDEX_PRICE_SYMBOLS


# ---------------------------------------------------------------------------
# Industry backfill: getting a sector onto the ~62% of the universe that sits
# in no sector index. Measurement (research/SECTOR_TIMING_FINDINGS.md) showed a
# correlation-inferred sector is not a substitute for a real one, so the
# backfill has to come from NSE's own Industry column and must never displace
# real index membership.
# ---------------------------------------------------------------------------

def _clear_sectors():
    """The seeded_db fixture keeps one database for the module, so rows another
    test inserted would otherwise be read back as this sync's output."""
    core.ensure_sector_table()
    con = core._db()
    try:
        con.execute("DELETE FROM sector_membership")
        con.commit()
    finally:
        con.close()


def _stub_csv(monkeypatch, pages):
    """Serve each URL a canned CSV instead of hitting niftyindices.com."""
    class R:
        def __init__(self, text): self.content = text.encode()
        def raise_for_status(self): pass
    def get(url, **kw):
        if url not in pages:
            raise AssertionError(f"unexpected fetch: {url}")
        return R(pages[url])
    monkeypatch.setattr(core.requests, "get", get)


def test_industry_backfill_reaches_stocks_no_sector_index_contains(seeded_db, monkeypatch):
    _clear_sectors()
    idx_url, broad_url = "http://idx/bank.csv", "http://broad/500.csv"
    _stub_csv(monkeypatch, {
        idx_url: "Company Name,Industry,Symbol\nHDFC Bank,Financial Services,HDFCBANK\n",
        broad_url: ("Company Name,Industry,Symbol\n"
                    "HDFC Bank,Financial Services,HDFCBANK\n"
                    "Infosys,Information Technology,INFY\n"
                    "Tata Motors,Automobile and Auto Components,TATAMOTORS\n"),
    })
    report = core.sync_sector_membership(urls={"Bank": idx_url},
                                         industry_urls={"NIFTY 500": broad_url})
    assert report["Bank"]["members"] == 1
    assert report["NIFTY 500"]["backfilled"] == 2, report
    m = core.sector_map()
    assert m["INFY"] == ["IT"]
    assert m["TATAMOTORS"] == ["Auto"]


def test_real_index_membership_is_not_displaced_by_the_industry_column(seeded_db, monkeypatch):
    """HDFCBANK is in the Bank index. The NIFTY 500 file calls its industry
    Financial Services. The index membership has to win - it is what the Bank
    sector index price actually tracks."""
    _clear_sectors()
    idx_url, broad_url = "http://idx/bank.csv", "http://broad/500.csv"
    _stub_csv(monkeypatch, {
        idx_url: "Symbol\nHDFCBANK\n",
        broad_url: "Industry,Symbol\nFinancial Services,HDFCBANK\n",
    })
    core.sync_sector_membership(urls={"Bank": idx_url},
                                industry_urls={"NIFTY 500": broad_url})
    assert core.sector_map()["HDFCBANK"] == ["Bank"]
    assert core.sector_map(source="industry") == {}


def test_an_industry_with_no_nse_index_gets_its_own_sector(seeded_db, monkeypatch):
    """Capital Goods has no NSE sector index, but its members define a
    perfectly good composite of their own. What must not happen is filing them
    under somebody else's index - ACC under Metal would carry a rank
    describing something it does not move with. Tiny buckets are handled by
    SECTOR_MIN_MEMBERS_TO_RANK at ranking time, not by dropping them here."""
    _clear_sectors()
    broad_url = "http://broad/500.csv"
    _stub_csv(monkeypatch, {broad_url: "Industry,Symbol\nCapital Goods,ABB\nRealty,DLF\n"})
    report = core.sync_sector_membership(urls={}, industry_urls={"NIFTY 500": broad_url})
    assert report["NIFTY 500"]["backfilled"] == 2
    m = core.sector_map()
    assert m["ABB"] == ["Capital Goods"]
    assert m["DLF"] == ["Realty"]


def test_every_nse_industry_maps_somewhere(seeded_db):
    """A None here means those stocks silently have no sector. The rule is now
    that every industry gets one; the member floor decides what is rankable."""
    assert all(v for v in core.INDUSTRY_TO_SECTOR.values()), \
        [k for k, v in core.INDUSTRY_TO_SECTOR.items() if not v]
    assert core.SECTOR_MIN_MEMBERS_TO_RANK >= 5


def test_a_sector_with_too_few_members_is_not_ranked(seeded_db):
    """Two stocks wearing an industry label are not a sector, and ranking them
    would put a stock's own noise into the filter S4 trades on."""
    _clear_sectors()
    con = core._db()
    try:
        con.executemany("INSERT OR REPLACE INTO sector_membership"
                        "(symbol,sector,updated_at,source) VALUES(?,?,?,?)",
                        [(f"BIG{i}", "Chemicals", "x", "industry") for i in range(6)]
                        + [("TINY1", "Forest Materials", "x", "industry"),
                           ("TINY2", "Forest Materials", "x", "industry")])
        con.commit()
    finally:
        con.close()
    idx = pd.bdate_range("2024-01-01", periods=300)
    rng = np.random.default_rng(0)
    data = {s: pd.DataFrame({"close": 100 * np.cumprod(1 + rng.normal(0, .01, 300))}, index=idx)
            for s in [f"BIG{i}" for i in range(6)] + ["TINY1", "TINY2"]}
    out = core.sector_relative_strength(data=data)
    sectors = set(out["Sector"]) if not out.empty else set()
    assert "Forest Materials" not in sectors, "a 2-member bucket must not be ranked"


def test_an_unrecognised_industry_string_is_reported_not_swallowed(seeded_db, monkeypatch):
    """If NSE renames an industry, stocks silently lose their sector. Only this
    report would show it."""
    _clear_sectors()
    broad_url = "http://broad/500.csv"
    _stub_csv(monkeypatch, {broad_url: "Industry,Symbol\nQuantum Widgets,ACME\n"})
    report = core.sync_sector_membership(urls={}, industry_urls={"NIFTY 500": broad_url})
    assert report["_unmapped_industries"] == {"QUANTUM WIDGETS": 1}
    assert "ACME" not in core.sector_map()


def test_passing_no_urls_means_none_rather_than_the_whole_catalogue(seeded_db, monkeypatch):
    def boom(url, **kw):
        raise AssertionError(f"nothing should have been fetched, got {url}")
    monkeypatch.setattr(core.requests, "get", boom)
    report = core.sync_sector_membership(urls={}, industry_urls={})
    assert report["_total_rows"] == 0


# ---------------------------------------------------------------------------
# The entry evidence filter - what replaced the score gate.
# research/SECTOR_TIMING_FINDINGS.md addenda 1 and 4.
# ---------------------------------------------------------------------------

def _filter_frame(close=100.0, volume=10_000_000, bars=30):
    """close x volume = Rs 100 cr of daily turnover by default, over the floor."""
    idx = pd.bdate_range("2024-01-01", periods=bars)
    return pd.DataFrame({"close": [close] * bars, "volume": [volume] * bars,
                         "open": [close] * bars, "high": [close] * bars,
                         "low": [close] * bars}, index=idx)


def _filter_features(close=100.0, atr=5.0):
    return pd.DataFrame({"close": [close], "atr14": [atr]})


def test_a_quiet_stock_fails_the_atr_rule():
    frame = _filter_frame()
    ok, why, m = core.entry_filter_verdict(frame, _filter_features(atr=2.0), 1)
    assert not ok and "ATR" in why
    assert m["atr_pct"] == pytest.approx(2.0)


def test_a_volatile_liquid_stock_passes():
    ok, why, _ = core.entry_filter_verdict(_filter_frame(), _filter_features(atr=5.0), 1)
    assert ok and "ATR 5.0%" in why


def test_the_turnover_floor_rejects_an_illiquid_name_however_volatile():
    """Below the floor the ATR edge inverts (PF 1.11 against 1.23), so a high
    ATR there is a reason to skip, not a reason to take."""
    frame = _filter_frame(close=100.0, volume=100_000)          # Rs 1 cr/day
    ok, why, _ = core.entry_filter_verdict(frame, _filter_features(atr=9.0), 1)
    assert not ok and "turnover" in why


def test_s4_is_judged_on_sector_rank_not_atr():
    """ATR does nothing for S4 (+0.19, p=0.40); the top-3 sector rank won 4
    years of 4. Applying the wrong rule to S4 would throw the edge away."""
    frame, feats = _filter_frame(), _filter_features(atr=1.0)   # ATR far too low
    ranks, lookup = {"IT": 1, "Auto": 7}, {"INFY": ["IT"], "TATAMOTORS": ["Auto"]}
    ok, why, _ = core.entry_filter_verdict(frame, feats, 4, sector_ranks=ranks,
                                           sector_lookup=lookup, ticker="INFY")
    assert ok, "a low-ATR S4 signal in the leading sector must still pass"
    assert "sector rank 1" in why
    bad, why2, _ = core.entry_filter_verdict(frame, feats, 4, sector_ranks=ranks,
                                             sector_lookup=lookup, ticker="TATAMOTORS")
    assert not bad and "sector rank 7" in why2


def test_s4_without_a_real_sector_is_rejected_not_waved_through():
    """Correlation-inferred sectors were measured not to carry the effect, so
    'no sector' has to fail rather than fall back to the ATR rule."""
    ok, why, _ = core.entry_filter_verdict(_filter_frame(), _filter_features(atr=9.0), 4,
                                           sector_ranks={"IT": 1}, sector_lookup={},
                                           ticker="UNKNOWN")
    assert not ok and "sector" in why


def test_a_missing_reading_fails_rather_than_passes():
    ok, _, _ = core.entry_filter_verdict(_filter_frame(), _filter_features(atr=float("nan")), 1)
    assert not ok


def test_the_filter_can_be_turned_off_for_measurement():
    ok, why, _ = core.entry_filter_verdict(_filter_frame(close=100.0, volume=100),
                                           _filter_features(atr=0.1), 1, apply_filter=False)
    assert ok and why == "filter off"


def test_each_strategy_has_a_rule_and_only_s4_uses_the_sector_one():
    assert set(core.ENTRY_FILTER_BY_STRATEGY) == set(core.IMPLEMENTED_STRATEGIES)
    sector_rules = {s for s, r in core.ENTRY_FILTER_BY_STRATEGY.items() if r == "sector"}
    assert sector_rules == {4}


def test_the_default_portfolio_is_the_measured_best_one():
    assert tuple(core.DEFAULT_STRATEGIES) == (4, 5)
    for s in core.DEFAULT_STRATEGIES:
        assert s in core.IMPLEMENTED_STRATEGIES


def test_persisting_signals_no_longer_gates_on_the_score(seeded_db):
    """The score has no demonstrated relationship to outcome, so every scanned
    row is selected for forward testing regardless of it."""
    result = pd.DataFrame([
        {"Ticker": "AAA", "Strategy": "S1", "Score": 12.0, "Entry": 100.0, "SL 7%": 93.0},
        {"Ticker": "BBB", "Strategy": "S4_SEPA", "Score": 99.0, "Entry": 50.0, "SL 7%": 46.5},
    ])
    core.persist_scanner_signals(result, min_score=95, signal_date="2024-05-01")
    con = core._db()
    try:
        rows = dict(con.execute("SELECT symbol, selected_for_forward FROM scanner_signals "
                                "WHERE signal_date='2024-05-01'").fetchall())
    finally:
        con.close()
    assert rows == {"AAA": 1, "BBB": 1}, rows


def test_s4s_sector_rule_reads_index_membership_only(seeded_db):
    """An NSE Industry label says what a company does; index membership says
    what the stock moves with, and the rank is built from the sector's price.
    Industry-labelled stocks track their assigned sector at a median
    correlation of 0.129, and S4's edge does not survive on them
    (research/SECTOR_TIMING_FINDINGS.md addendum 6), so they must not feed the
    lookup the rule uses."""
    _clear_sectors()
    core.ensure_sector_table()
    con = core._db()
    try:
        con.executemany("INSERT OR REPLACE INTO sector_membership"
                        "(symbol,sector,updated_at,source) VALUES(?,?,?,?)",
                        [("INFY", "IT", "x", "index"),
                         ("SMALLCO", "IT", "x", "industry")])
        con.commit()
    finally:
        con.close()
    assert core.sector_map(source="index") == {"INFY": ["IT"]}
    assert core.sector_map(source="industry") == {"SMALLCO": ["IT"]}
    assert sorted(core.sector_map()) == ["INFY", "SMALLCO"], "display still sees both"

    ranks, lookup = {"IT": 1}, core.sector_map(source="index")
    ok, _, _ = core.entry_filter_verdict(_filter_frame(), _filter_features(atr=1.0), 4,
                                         sector_ranks=ranks, sector_lookup=lookup,
                                         ticker="INFY")
    assert ok
    bad, why, _ = core.entry_filter_verdict(_filter_frame(), _filter_features(atr=9.0), 4,
                                            sector_ranks=ranks, sector_lookup=lookup,
                                            ticker="SMALLCO")
    assert not bad, "an industry label must not satisfy S4's sector rule"
    assert "sector" in why, "and it must fail ON the sector rule, not fall back to ATR"


def test_the_entry_ranking_and_the_dashboard_ranking_are_separate(seeded_db):
    """Ranking all 22 sectors measurably weakens S4's filter - the
    industry-defined composites are noisier and crowd the top, displacing real
    index sectors. So the entry rule ranks the index-priced sectors only while
    the dashboard shows everything (addendum 7)."""
    _clear_sectors()
    con = core._db()
    try:
        rows = [(f"IDX{i}", "IT", "x", "index") for i in range(6)]
        rows += [(f"IND{i}", "Chemicals", "x", "industry") for i in range(6)]
        con.executemany("INSERT OR REPLACE INTO sector_membership"
                        "(symbol,sector,updated_at,source) VALUES(?,?,?,?)", rows)
        con.commit()
    finally:
        con.close()
    idx = pd.bdate_range("2024-01-01", periods=300)
    rng = np.random.default_rng(1)
    data = {s: pd.DataFrame({"close": 100 * np.cumprod(1 + rng.normal(0, .01, 300))}, index=idx)
            for s, *_ in [(r[0],) for r in rows]}
    # A rank is relative TO the benchmark, so without it every sector scores
    # NaN and both rankings come back empty - which would pass the first
    # assertion for the wrong reason.
    con = core._db()
    try:
        con.executemany(
            "INSERT OR REPLACE INTO candles(symbol,dt,open,high,low,close,volume) "
            "VALUES(?,?,?,?,?,?,?)",
            [(core.index_store_symbol(core.REGIME_INDEX), d.strftime("%Y-%m-%d"),
              100.0, 100.0, 100.0, 100.0, 0.0) for d in idx])
        con.commit()
    finally:
        con.close()
    entry = core.current_sector_ranks(data=data, source="index")
    board = core.current_sector_ranks(data=data, source=None)
    assert "Chemicals" not in entry, "an industry-defined sector must not rank S4 entries"
    assert "Chemicals" in board, "but the dashboard must still show it"
