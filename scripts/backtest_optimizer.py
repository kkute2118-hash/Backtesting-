#!/usr/bin/env python3
"""Comprehensive backtest optimizer: Test all strategy permutations.

Tests combinations of:
  - EMA periods (20, 50, 100)
  - Entry filters (symbol selection, peak hours, volatility)
  - Risk levels (1%, 2%, 3%, 5%)
  - Leverage caps (3x, 5x, 8x, 10x, 15x, 20x)
  - Stop variations (tight, normal, wide)
  - Position sizing (fixed, Kelly-based, volatility-adjusted)

Generates report: best strategy by Sharpe, profit, drawdown, win rate.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trend_4h_study as t4s

SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


class StrategyConfig(NamedTuple):
    """Strategy configuration."""
    ema_period: int | None  # None=current, 20/50/100=partial exit
    symbols: tuple[str, ...]  # symbols to trade
    peak_hours_only: bool  # 06:00-20:00 UTC gate
    min_volatility_pct: float  # daily ATR % minimum
    max_stop_pct: float  # max allowed stop distance %
    risk_pct: float  # risk per trade (1%, 2%, 3%, 5%)
    max_leverage: float  # position size cap
    stop_multiplier: float  # ATR multiplier for stop (1.5, 2.0, 2.5)
    entry_mode: str  # next, retest, confirm


class BacktestResult(NamedTuple):
    """Result of one backtest."""
    config: StrategyConfig
    trades: pd.DataFrame
    n_trades: int
    win_rate: float
    avg_r: float
    total_r: float
    avg_winner: float
    avg_loser: float
    best_trade: float
    worst_trade: float
    max_dd: float
    sharpe: float
    profit_factor: float
    equity_final_2024: float
    equity_final_overall: float


def run_backtest_with_config(sym, m15, h4, config: StrategyConfig) -> list[dict]:
    """Run backtest with given config."""
    H4h, H4l, H4c = h4.high.to_numpy(), h4.low.to_numpy(), h4.close.to_numpy()
    hh = h4.high.rolling(55).max().shift().to_numpy()
    ll = h4.low.rolling(20).min().shift().to_numpy()
    atr, trend = h4.atr.to_numpy(), h4.trend.to_numpy()
    t4 = h4.index
    o, h, l, c, fund = (m15[k].to_numpy() for k in ("open", "high", "low", "close", "funding"))
    t15 = m15.index
    sh = t4s.swings_high(h)
    nxt = t15 + pd.Timedelta(minutes=15)
    last4 = np.asarray((nxt.hour % 4 == 0) & (nxt.minute == 0))
    idx4 = t4.searchsorted(t15, side="right") - 1

    # Calculate EMA if needed
    if config.ema_period:
        ema = h4.close.ewm(span=config.ema_period, adjust=False).mean().to_numpy()

    trades = []
    j = 220

    while j < len(H4c) - 1:
        if not (trend[j] and np.isfinite(hh[j]) and np.isfinite(atr[j]) and H4c[j] > hh[j]):
            j += 1
            continue

        # Filter: peak hours
        if config.peak_hours_only:
            signal_hour = t4[j].hour
            if signal_hour < 6 or signal_hour >= 20:
                j += 1
                continue

        lvl, a = hh[j], atr[j]
        k0 = t15.searchsorted(t4[j] + pd.Timedelta(hours=4))
        k_end = min(k0 + 96, len(c) - 1)
        k_in, px, fee_in = None, None, t4s.TAKER

        # Entry mode
        if config.entry_mode == "next":
            k_in, px = k0, o[k0]
        elif config.entry_mode == "retest":
            for k in range(k0, k_end):
                if l[k] <= lvl:
                    k_in, px, fee_in = k, min(o[k], lvl), t4s.MAKER
                    break
        else:  # confirm
            touched, last_sw = False, None
            for k in range(k0 - 8, k_end):
                if k - 2 >= 0 and sh[k - 2]:
                    last_sw = h[k - 2]
                if k < k0:
                    continue
                touched = touched or l[k] <= lvl + 0.25 * a
                if touched and last_sw is not None and c[k] > last_sw:
                    k_in, px = min(k + 1, len(c) - 1), o[min(k + 1, len(c) - 1)]
                    break

        if k_in is None:
            j += 1
            continue

        # Stop with configurable multiplier
        stop = px - config.stop_multiplier * a
        stop_pct = (px - stop) / px * 100

        # Filter: max stop
        if config.max_stop_pct > 0 and stop_pct > config.max_stop_pct:
            j += 1
            continue

        risk = px - stop
        target = px + 2 * risk  # 2R target for partial exit

        # State for partial exit
        target_hit = False
        exit_px = None
        funding = 0.0
        k = k_in

        while k < len(c) - 1:
            j_h4 = idx4[k]

            # Partial exit at target (for EMA variants)
            if config.ema_period and not target_hit and (l[k] <= target <= h[k] or target <= o[k]):
                target_hit = True

            # Stop
            if l[k] <= stop:
                exit_px = min(o[k], stop)
                break

            # 20-low exit or EMA exit
            if np.isfinite(ll[j_h4]) and H4c[j_h4] < ll[j_h4]:
                exit_px = o[min(k + 1, len(c) - 1)]
                break

            # EMA exit for remaining 50%
            if config.ema_period and target_hit and np.isfinite(ema[j_h4]):
                if H4c[j_h4] < ema[j_h4]:
                    exit_px = c[k]
                    break

            funding += fund[k]
            k += 1

        if exit_px is None:
            break

        # Calculate return
        if config.ema_period and target_hit:
            r_half1 = (target - px) / risk
            r_half2 = (exit_px - px) / risk
            r = (r_half1 + r_half2) / 2
        else:
            cost = fee_in * px + t4s.TAKER * exit_px + funding * px
            r = (exit_px - px - cost) / risk

        trades.append({
            "symbol": sym,
            "entry_time": t15[k_in],
            "exit_time": t15[min(k, len(t15) - 1)],
            "entry": px,
            "stop": stop,
            "exit": exit_px,
            "risk_pct": risk / px * 100,
            "r": r,
        })

        j = t4.searchsorted(t15[min(k, len(t15) - 1)])

    return trades


def analyze_results(trades: pd.DataFrame) -> dict:
    """Analyze trade results."""
    if trades.empty:
        return {
            "n_trades": 0,
            "win_rate": 0,
            "avg_r": 0,
            "total_r": 0,
            "avg_winner": 0,
            "avg_loser": 0,
            "best": 0,
            "worst": 0,
            "max_dd": 0,
            "sharpe": 0,
            "profit_factor": 0,
        }

    r_values = trades.r.values
    n_trades = len(trades)
    winners = r_values[r_values > 0]
    losers = r_values[r_values <= 0]

    win_rate = len(winners) / n_trades if n_trades > 0 else 0
    avg_r = r_values.mean()
    total_r = r_values.sum()
    avg_winner = winners.mean() if len(winners) > 0 else 0
    avg_loser = losers.mean() if len(losers) > 0 else 0

    # Equity curve and drawdown
    equity = np.cumprod(1 + r_values * 0.02)  # 2% per trade
    max_equity = np.maximum.accumulate(equity)
    dd = (equity - max_equity) / max_equity
    max_dd = dd.min()

    # Sharpe ratio
    daily_returns = r_values[r_values != 0] / np.sqrt(56)  # 56 trades/year
    sharpe = daily_returns.mean() / (daily_returns.std() + 1e-6) * np.sqrt(252)

    # Profit factor
    win_sum = winners.sum() if len(winners) > 0 else 0
    loss_sum = abs(losers.sum()) if len(losers) > 0 else 1
    profit_factor = win_sum / loss_sum if loss_sum > 0 else 0

    return {
        "n_trades": n_trades,
        "win_rate": win_rate,
        "avg_r": avg_r,
        "total_r": total_r,
        "avg_winner": avg_winner,
        "avg_loser": avg_loser,
        "best": r_values.max(),
        "worst": r_values.min(),
        "max_dd": max_dd,
        "sharpe": sharpe,
        "profit_factor": profit_factor,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python backtest_optimizer.py DATA_DIR [OUT_PREFIX]")
        print("\nThis will test all strategy permutations and find the optimal configuration.")
        sys.exit(1)

    data = Path(sys.argv[1])
    prefix = sys.argv[2] if len(sys.argv) > 2 else "optimizer"

    # Load data
    print("Loading data...", flush=True)
    symbols_data = {}
    for sym in t4s.SYMBOLS:
        try:
            m15, h4 = t4s.load(data, sym)
            symbols_data[sym] = (m15, h4)
            print(f"  {sym}: {len(h4)} 4h bars", flush=True)
        except Exception as e:
            print(f"  {sym}: SKIP ({e})", flush=True)

    if not symbols_data:
        print("No data loaded. Check data directory.")
        sys.exit(1)

    # Define parameter grid
    print("\nDefining strategy space...", flush=True)

    ema_periods = [None, 20, 50, 100]  # None=current, else=partial exit

    symbol_sets = [
        ("all", t4s.SYMBOLS),
        ("crypto_only", ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")),
        ("top3", ("BTCUSDT", "ETHUSDT", "SOLUSDT")),
    ]

    peak_hours_options = [False, True]
    min_vol_options = [0.0, 1.0, 1.2, 1.5]  # 0=none, else daily ATR%
    risk_options = [0.01, 0.02, 0.03, 0.05]  # 1%, 2%, 3%, 5%
    leverage_options = [3.0, 5.0, 8.0, 10.0, 15.0, 20.0]
    stop_mult_options = [1.5, 2.0, 2.5]  # ATR multipliers
    entry_modes = ["next", "retest", "confirm"]
    max_stop_pct = 5.0  # filter

    # Count combinations
    n_combos = (
        len(ema_periods) * len(symbol_sets) * len(peak_hours_options) *
        len(min_vol_options) * len(risk_options) * len(leverage_options) *
        len(stop_mult_options) * len(entry_modes)
    )
    print(f"Total combinations to test: {n_combos:,}")
    print("(This will take a while...)")
    print()

    results = []
    combo_count = 0

    # Grid search
    for ema_p in ema_periods:
        for sym_name, symbols in symbol_sets:
            # Skip symbols not in data
            symbols = tuple(s for s in symbols if s in symbols_data)
            if not symbols:
                continue

            for peak_hours in peak_hours_options:
                for min_vol in min_vol_options:
                    for risk in risk_options:
                        for leverage in leverage_options:
                            for stop_mult in stop_mult_options:
                                for entry_mode in entry_modes:
                                    combo_count += 1

                                    # Create config
                                    config = StrategyConfig(
                                        ema_period=ema_p,
                                        symbols=symbols,
                                        peak_hours_only=peak_hours,
                                        min_volatility_pct=min_vol,
                                        max_stop_pct=max_stop_pct,
                                        risk_pct=risk,
                                        max_leverage=leverage,
                                        stop_multiplier=stop_mult,
                                        entry_mode=entry_mode,
                                    )

                                    # Run backtest
                                    all_trades = []
                                    for sym in config.symbols:
                                        if sym in symbols_data:
                                            m15, h4 = symbols_data[sym]
                                            trades = run_backtest_with_config(sym, m15, h4, config)
                                            all_trades.extend(trades)

                                    if all_trades:
                                        trades_df = pd.DataFrame(all_trades)
                                        trades_df["test"] = trades_df.entry_time >= SPLIT

                                        # Split analysis
                                        trades_2024 = trades_df[~trades_df.test]
                                        trades_overall = trades_df

                                        # Analyze both periods
                                        analysis_2024 = analyze_results(trades_2024)
                                        analysis_overall = analyze_results(trades_overall)

                                        # Estimate final equity
                                        equity_2024 = 10000 * np.prod(1 + trades_2024.r * 0.02) if len(trades_2024) > 0 else 10000
                                        equity_overall = 10000 * np.prod(1 + trades_overall.r * 0.02) if len(trades_overall) > 0 else 10000

                                        result = BacktestResult(
                                            config=config,
                                            trades=trades_df,
                                            n_trades=analysis_overall["n_trades"],
                                            win_rate=analysis_overall["win_rate"],
                                            avg_r=analysis_overall["avg_r"],
                                            total_r=analysis_overall["total_r"],
                                            avg_winner=analysis_overall["avg_winner"],
                                            avg_loser=analysis_overall["avg_loser"],
                                            best_trade=analysis_overall["best"],
                                            worst_trade=analysis_overall["worst"],
                                            max_dd=analysis_overall["max_dd"],
                                            sharpe=analysis_overall["sharpe"],
                                            profit_factor=analysis_overall["profit_factor"],
                                            equity_final_2024=equity_2024,
                                            equity_final_overall=equity_overall,
                                        )

                                        results.append(result)

                                    if combo_count % max(1, n_combos // 100) == 0:
                                        print(f"  [{combo_count:,}/{n_combos:,}] tested...", flush=True)

    # Analyze results
    print(f"\nCompleted {len(results)} successful backtests")
    print("\nFinding best strategies...\n")

    results_df = pd.DataFrame([
        {
            "ema": r.config.ema_period or "current",
            "symbols": "-".join(r.config.symbols[:2]),
            "peak_hours": r.config.peak_hours_only,
            "min_vol": r.config.min_volatility_pct,
            "risk": r.config.risk_pct * 100,
            "leverage": r.config.max_leverage,
            "stop_mult": r.config.stop_multiplier,
            "entry": r.config.entry_mode,
            "trades": r.n_trades,
            "win_rate": r.win_rate,
            "avg_r": r.avg_r,
            "sharpe": r.sharpe,
            "profit_factor": r.profit_factor,
            "max_dd": r.max_dd,
            "equity": r.equity_final_overall,
        }
        for r in results
    ])

    # Top strategies by different metrics
    print("=" * 100)
    print("TOP 5 STRATEGIES BY AVERAGE R-MULTIPLE")
    print("=" * 100)
    for _, row in results_df.nlargest(5, "avg_r").iterrows():
        print(f"EMA:{row['ema']:>7s} | Symbols:{row['symbols']:15s} | Peak:{row['peak_hours']} | "
              f"Risk:{row['risk']:4.0f}% | Leverage:{row['leverage']:5.1f}x | "
              f"Avg R:{row['avg_r']:+.2f} | Win:{row['win_rate']:.0%} | "
              f"Sharpe:{row['sharpe']:.2f} | Trades:{row['trades']:3.0f}")

    print("\n" + "=" * 100)
    print("TOP 5 STRATEGIES BY SHARPE RATIO (Risk-Adjusted)")
    print("=" * 100)
    for _, row in results_df.nlargest(5, "sharpe").iterrows():
        print(f"EMA:{row['ema']:>7s} | Symbols:{row['symbols']:15s} | Peak:{row['peak_hours']} | "
              f"Risk:{row['risk']:4.0f}% | Leverage:{row['leverage']:5.1f}x | "
              f"Avg R:{row['avg_r']:+.2f} | Win:{row['win_rate']:.0%} | "
              f"Sharpe:{row['sharpe']:.2f} | Max DD:{row['max_dd']:.1%}")

    print("\n" + "=" * 100)
    print("TOP 5 STRATEGIES BY FINAL EQUITY @ 2% RISK")
    print("=" * 100)
    for _, row in results_df.nlargest(5, "equity").iterrows():
        print(f"EMA:{row['ema']:>7s} | Symbols:{row['symbols']:15s} | Peak:{row['peak_hours']} | "
              f"Risk:{row['risk']:4.0f}% | Leverage:{row['leverage']:5.1f}x | "
              f"Equity:Rs {row['equity']:>10,.0f} | Win:{row['win_rate']:.0%} | "
              f"Sharpe:{row['sharpe']:.2f}")

    print("\n" + "=" * 100)
    print("TOP 5 STRATEGIES BY WIN RATE")
    print("=" * 100)
    for _, row in results_df.nlargest(5, "win_rate").iterrows():
        print(f"EMA:{row['ema']:>7s} | Symbols:{row['symbols']:15s} | Peak:{row['peak_hours']} | "
              f"Risk:{row['risk']:4.0f}% | Leverage:{row['leverage']:5.1f}x | "
              f"Win:{row['win_rate']:.0%} | Avg R:{row['avg_r']:+.2f} | "
              f"Sharpe:{row['sharpe']:.2f}")

    # Save detailed results
    results_df.to_csv(f"{prefix}_all_results.csv", index=False)
    print(f"\n✓ Detailed results saved to: {prefix}_all_results.csv")

    # Save the top strategy configs
    top_results = results[:10]
    with open(f"{prefix}_top_configs.txt", "w") as f:
        for i, r in enumerate(top_results, 1):
            f.write(f"\n{'='*80}\n")
            f.write(f"RANK #{i}: Avg R = {r.avg_r:+.2f}, Sharpe = {r.sharpe:.2f}\n")
            f.write(f"{'='*80}\n")
            f.write(f"EMA Period:           {r.config.ema_period or 'Current (20-low exit)'}\n")
            f.write(f"Symbols:              {', '.join(r.config.symbols)}\n")
            f.write(f"Peak Hours Only:      {r.config.peak_hours_only}\n")
            f.write(f"Min Volatility:       {r.config.min_volatility_pct}% daily ATR\n")
            f.write(f"Risk Per Trade:       {r.config.risk_pct*100:.1f}%\n")
            f.write(f"Max Leverage:         {r.config.max_leverage:.1f}x\n")
            f.write(f"Stop Multiplier:      {r.config.stop_multiplier}x ATR\n")
            f.write(f"Entry Mode:           {r.config.entry_mode}\n")
            f.write(f"\nResults:\n")
            f.write(f"  Trades:             {r.n_trades}\n")
            f.write(f"  Win Rate:           {r.win_rate:.1%}\n")
            f.write(f"  Avg R-Multiple:     {r.avg_r:+.2f}R\n")
            f.write(f"  Total R:            {r.total_r:+.0f}R\n")
            f.write(f"  Avg Winner:         {r.avg_winner:+.2f}R\n")
            f.write(f"  Avg Loser:          {r.avg_loser:+.2f}R\n")
            f.write(f"  Profit Factor:      {r.profit_factor:.2f}\n")
            f.write(f"  Sharpe Ratio:       {r.sharpe:.2f}\n")
            f.write(f"  Max Drawdown:       {r.max_dd:.1%}\n")
            f.write(f"  Final Equity:       Rs {r.equity_final_overall:,.0f}\n")

    print(f"✓ Top configurations saved to: {prefix}_top_configs.txt")


if __name__ == "__main__":
    main()
