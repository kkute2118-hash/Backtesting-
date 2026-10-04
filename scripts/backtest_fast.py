#!/usr/bin/env python3
"""Fast backtest: Test only the most promising configurations.

Focuses on:
  - EMA20, EMA50 (skip EMA100)
  - Top3 symbols (BTC/ETH/SOL), crypto_only
  - Peak hours: yes, no
  - Volatility: 0%, 1.2%
  - Risk: 2% (optimal from research)
  - Leverage: 5x (natural cap)
  - Stop: 2.0x ATR (optimal)
  - Entry: next, retest (skip confirm, slower)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trend_4h_study as t4s

SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def run_quick_backtest(sym, m15, h4, config):
    """Fast backtest with config."""
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
    if config["ema"]:
        ema = h4.close.ewm(span=config["ema"], adjust=False).mean().to_numpy()

    trades = []
    j = 220

    while j < len(H4c) - 1:
        if not (trend[j] and np.isfinite(hh[j]) and np.isfinite(atr[j]) and H4c[j] > hh[j]):
            j += 1
            continue

        # Peak hours filter
        if config["peak_hours"] and (t4[j].hour < 6 or t4[j].hour >= 20):
            j += 1
            continue

        lvl, a = hh[j], atr[j]
        k0 = t15.searchsorted(t4[j] + pd.Timedelta(hours=4))
        k_end = min(k0 + 96, len(c) - 1)
        k_in, px, fee_in = None, None, t4s.TAKER

        if config["entry"] == "next":
            k_in, px = k0, o[k0]
        else:  # retest
            for k in range(k0, k_end):
                if l[k] <= lvl:
                    k_in, px, fee_in = k, min(o[k], lvl), t4s.MAKER
                    break

        if k_in is None:
            j += 1
            continue

        stop = px - 2.0 * a
        risk = px - stop

        # Volatility filter
        if config["min_vol"] > 0:
            # Estimate daily ATR
            j_daily = j
            daily_atr = atr[j_daily] if np.isfinite(atr[j_daily]) else 0
            daily_atr_pct = (daily_atr / px * 100) if px > 0 else 0
            if daily_atr_pct < config["min_vol"]:
                j += 1
                continue

        target = px + 2 * risk
        target_hit = False
        exit_px = None
        funding = 0.0
        k = k_in

        while k < len(c) - 1:
            j_h4 = idx4[k]

            # Partial exit
            if config["ema"] and not target_hit and l[k] <= target <= h[k]:
                target_hit = True

            if l[k] <= stop:
                exit_px = min(o[k], stop)
                break

            if np.isfinite(ll[j_h4]) and H4c[j_h4] < ll[j_h4]:
                exit_px = o[min(k + 1, len(c) - 1)]
                break

            if config["ema"] and target_hit and np.isfinite(ema[j_h4]):
                if H4c[j_h4] < ema[j_h4]:
                    exit_px = c[k]
                    break

            funding += fund[k]
            k += 1

        if exit_px is None:
            break

        if config["ema"] and target_hit:
            r = ((target - px) + (exit_px - px)) / 2 / risk
        else:
            cost = fee_in * px + t4s.TAKER * exit_px + funding * px
            r = (exit_px - px - cost) / risk

        trades.append({
            "symbol": sym,
            "entry_time": t15[k_in],
            "r": r,
        })

        j = t4.searchsorted(t15[min(k, len(t15) - 1)])

    return trades


def main():
    if len(sys.argv) < 2:
        print("Usage: python backtest_fast.py DATA_DIR")
        sys.exit(1)

    data = Path(sys.argv[1])

    print("Loading data...", flush=True)
    symbols_data = {}
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"):
        try:
            m15, h4 = t4s.load(data, sym)
            symbols_data[sym] = (m15, h4)
            print(f"  ✓ {sym}", flush=True)
        except Exception as e:
            print(f"  ✗ {sym}: {e}", flush=True)

    if not symbols_data:
        print("No data loaded")
        sys.exit(1)

    print("\nTesting key configurations...\n")

    configs = [
        {"name": "Baseline (current)", "ema": None, "peak_hours": False, "min_vol": 0, "entry": "next"},
        {"name": "+ Peak hours", "ema": None, "peak_hours": True, "min_vol": 0, "entry": "next"},
        {"name": "+ Volatility gate", "ema": None, "peak_hours": True, "min_vol": 1.2, "entry": "next"},
        {"name": "+ Retest entry", "ema": None, "peak_hours": True, "min_vol": 1.2, "entry": "retest"},
        {"name": "+ EMA20 trail", "ema": 20, "peak_hours": True, "min_vol": 1.2, "entry": "retest"},
        {"name": "+ EMA50 trail ⭐", "ema": 50, "peak_hours": True, "min_vol": 1.2, "entry": "retest"},
        {"name": "+ EMA100 trail", "ema": 100, "peak_hours": True, "min_vol": 1.2, "entry": "retest"},
    ]

    results = []

    for cfg in configs:
        all_trades = []
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            if sym in symbols_data:
                m15, h4 = symbols_data[sym]
                trades = run_quick_backtest(sym, m15, h4, cfg)
                all_trades.extend(trades)

        if not all_trades:
            print(f"{cfg['name']:<30} No trades")
            continue

        r_vals = np.array([t["r"] for t in all_trades])

        win_rate = (r_vals > 0).mean()
        avg_r = r_vals.mean()
        total_r = r_vals.sum()

        results.append({
            "config": cfg["name"],
            "trades": len(all_trades),
            "win_rate": win_rate,
            "avg_r": avg_r,
            "total_r": total_r,
        })

        print(f"{cfg['name']:<30} n={len(all_trades):3d} | win {win_rate:5.1%} | "
              f"avg {avg_r:+.2f}R | total {total_r:+.0f}R")

    print("\n" + "="*80)
    print("SUMMARY: Configuration Impact")
    print("="*80)

    results_df = pd.DataFrame(results)
    results_df.to_csv("results/fast_backtest.csv", index=False)

    print("\n✓ Results saved to: results/fast_backtest.csv")
    print("\nKey findings:")
    print(f"  Best by Avg R: {results_df.loc[results_df['avg_r'].idxmax(), 'config']}")
    print(f"  Best by Win Rate: {results_df.loc[results_df['win_rate'].idxmax(), 'config']}")
    print(f"  Best by Total R: {results_df.loc[results_df['total_r'].idxmax(), 'config']}")


if __name__ == "__main__":
    main()
