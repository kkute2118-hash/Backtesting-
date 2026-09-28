"""Portfolio replay and the Indian delivery cost model."""

from __future__ import annotations

import pandas as pd
import pytest

from app.engine.portfolio_bt import NO_COSTS, IndianDeliveryCosts, run_portfolio


def test_charges_on_one_lakh_match_a_hand_calculation():
    c = IndianDeliveryCosts(slippage_pct=0.0)
    # buy: STT 100 + exchange 2.97 + SEBI 0.10 + GST 18% of (2.97+0.10) + stamp 15
    assert c.buy(100_000) == pytest.approx(100 + 2.97 + 0.10 + 0.5526 + 15, abs=0.01)
    # sell: STT 100 + exchange 2.97 + SEBI 0.10 + GST 0.5526 + DP 12.5 * 1.18
    assert c.sell(100_000) == pytest.approx(100 + 2.97 + 0.10 + 0.5526 + 14.75, abs=0.01)
    assert c.round_trip_pct(100_000) == pytest.approx(0.2370, abs=0.001)


def _closes(days, **series):
    idx = pd.bdate_range("2026-01-05", periods=days)
    return pd.DataFrame({k: v for k, v in series.items()}, index=idx)


def _trade(strategy, symbol, entry_i, exit_i, idx, entry=100.0, stop=90.0, exit_=110.0, rank=3.0):
    return {"strategy": strategy, "symbol": symbol, "signal_date": idx[entry_i], "entry_date": idx[entry_i],
            "entry": entry, "stop": stop, "exit_date": idx[exit_i], "exit": exit_, "exit_reason": "X",
            "rank_key": rank}


def test_one_trade_sized_by_risk_without_costs():
    closes = _closes(10, AAA=[100.0] * 5 + [110.0] * 5)
    t = pd.DataFrame([_trade("S6_BREAKOUT", "AAA", 0, 5, closes.index)])
    r = run_portfolio(t, closes, capital=100_000, costs=NO_COSTS)
    fill = r.fills.iloc[0]
    assert fill.qty == 100                      # 1% of 1 lakh / Rs 10 risk per share
    assert r.stats["final"] == pytest.approx(101_000)
    assert r.stats["win_pct"] == 100.0


def test_slots_and_one_position_per_stock():
    idx = pd.bdate_range("2026-01-05", periods=10)
    closes = pd.DataFrame({s: [100.0] * 10 for s in ("A", "B", "C")}, index=idx)
    t = pd.DataFrame([
        _trade("S5_POCKETPIVOT", "A", 0, 8, idx, rank=5),
        _trade("S6_BREAKOUT", "A", 1, 8, idx),              # same stock again: skipped
        _trade("S5_POCKETPIVOT", "B", 0, 8, idx, rank=4),
        _trade("S5_POCKETPIVOT", "C", 0, 8, idx, rank=1),   # third on a 2-slot book: skipped
    ])
    r = run_portfolio(t, closes, max_positions=2, costs=NO_COSTS)
    assert sorted(r.fills.symbol) == ["A", "B"]
    assert r.skipped["held"] == 1 and r.skipped["no_slot"] == 1


def test_buckets_keep_strategies_apart():
    idx = pd.bdate_range("2026-01-05", periods=10)
    closes = pd.DataFrame({"A": [100.0] * 10, "B": [100.0] * 10}, index=idx)
    t = pd.DataFrame([_trade("S5_POCKETPIVOT", "A", 0, 5, idx), _trade("S6_BREAKOUT", "B", 0, 5, idx)])
    r = run_portfolio(t, closes, capital=100_000, max_positions=1, costs=NO_COSTS,
                      buckets={"S5_POCKETPIVOT": 0.5, "S6_BREAKOUT": 0.5})
    # each bucket is 50,000: 1% = 500 risk / Rs 10 = 50 shares
    assert list(r.fills.sort_values("symbol").qty) == [50, 50]
    assert set(r.bucket_equity.columns) == {"S5_POCKETPIVOT", "S6_BREAKOUT"}


def test_costs_reduce_the_result():
    closes = _closes(10, AAA=[100.0] * 5 + [110.0] * 5)
    t = pd.DataFrame([_trade("S6_BREAKOUT", "AAA", 0, 5, closes.index)])
    free = run_portfolio(t, closes, costs=NO_COSTS).stats["final"]
    real = run_portfolio(t, closes).stats["final"]
    assert real < free


def test_margin_doubles_the_position_and_charges_interest():
    # Entry 100, stop 90: 1x risks 1% (100 shares); 2x risks 2% (200 shares,
    # Rs 20,000 of stock, capped at 50% of value, all within cash here).
    closes = _closes(10, AAA=[100.0] * 5 + [110.0] * 5)
    t = pd.DataFrame([_trade("S6_BREAKOUT", "AAA", 0, 5, closes.index)])
    one = run_portfolio(t, closes, capital=100_000, costs=NO_COSTS)
    two = run_portfolio(t, closes, capital=100_000, costs=NO_COSTS, leverage=2.0, pledge_fee=0)
    assert one.fills.iloc[0].qty == 100 and two.fills.iloc[0].qty == 200
    assert one.stats["interest_paid"] == 0 and two.stats["final"] == pytest.approx(102_000)


def test_margin_borrows_past_cash_and_pays_interest_on_it():
    # Tiny risk per share: the position cap binds. 1x caps at 25% of value;
    # 4x at 100%, so four such trades need Rs 4 lakh on a Rs 1 lakh account.
    idx = pd.bdate_range("2026-01-05", periods=30)
    closes = pd.DataFrame({s: [100.0] * 30 for s in "ABCD"}, index=idx)
    t = pd.DataFrame([_trade("S6_BREAKOUT", s, 0, 29, idx, stop=99.0, exit_=100.0) for s in "ABCD"])
    cash = run_portfolio(t, closes, capital=100_000, costs=NO_COSTS)
    mtf = run_portfolio(t, closes, capital=100_000, costs=NO_COSTS, leverage=4.0, pledge_fee=20)
    assert cash.fills.qty.sum() == 1000                     # 4 x Rs 25,000
    assert mtf.fills.qty.sum() > 3000                       # borrowed about Rs 3 lakh
    days = (idx[-1] - idx[0]).days
    assert mtf.stats["interest_paid"] == pytest.approx(300_000 * 0.125 / 365 * days, rel=0.05)
    assert mtf.stats["final"] < 100_000                     # flat trades: interest + pledge are pure cost


def test_risk_can_be_set_per_strategy():
    idx = pd.bdate_range("2026-01-05", periods=10)
    closes = pd.DataFrame({s: [100.0] * 10 for s in ("A", "B")}, index=idx)
    t = pd.DataFrame([_trade("S5_POCKETPIVOT", "A", 0, 5, idx), _trade("S6_BREAKOUT", "B", 0, 5, idx)])
    r = run_portfolio(t, closes, costs=NO_COSTS, risk_by_strategy={"S5_POCKETPIVOT": 0.5})
    q = dict(zip(r.fills.symbol, r.fills.qty))
    assert q == {"A": 50, "B": 100}          # 0.5% and 1% of 1 lakh over Rs 10 risk
