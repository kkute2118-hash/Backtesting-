#!/usr/bin/env python3
"""Test entry timing filters on the 4h trend strategy.

Variants:
  baseline    original 55/20 strategy (no filters)
  no_gold     drop gold, keep crypto only
  no_xrp      drop XRP as well
  peak_hours  only trade during EU/US peak (06:00-20:00 UTC)
  all_filters conservative combination
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trend_4h_study as t4s

SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def run_filtered(sym, m15, h4, n_in, n_out, entry_mode, filters: dict):
    """Run the trend strategy with optional filters."""
    H4h, H4l, H4c = h4.high.to_numpy(), h4.low.to_numpy(), h4.close.to_numpy()
    hh = h4.high.rolling(n_in).max().shift().to_numpy()
    ll = h4.low.rolling(n_out).min().shift().to_numpy()
    atr, trend = h4.atr.to_numpy(), h4.trend.to_numpy()
    t4 = h4.index
    o, h, l, c, fund = (m15[k].to_numpy() for k in ("open", "high", "low", "close", "funding"))
    t15 = m15.index
    sh = t4s.swings_high(h)
    pos15 = t15.searchsorted
    nxt = t15 + pd.Timedelta(minutes=15)
    last4 = np.asarray((nxt.hour % 4 == 0) & (nxt.minute == 0))
    idx4 = t4.searchsorted(t15, side="right") - 1

    trades = []
    j = 220
    losing_streak = 0

    while j < len(H4c) - 1:
        if not (trend[j] and np.isfinite(hh[j]) and np.isfinite(atr[j]) and H4c[j] > hh[j]):
            j += 1
            continue

        # Filter: Skip if in losing streak
        if filters.get("skip_after_loss_streak", 0) > 0 and losing_streak >= 3:
            losing_streak = 0
            j += 1
            continue

        # Filter: Peak hours only (06:00-20:00 UTC)
        signal_time = t4[j]
        signal_hour = signal_time.hour
        if filters.get("peak_hours_only", False):
            if signal_hour < 6 or signal_hour >= 20:
                j += 1
                continue

        # Filter: Daily volatility check (daily ATR > 1.2% of price)
        j_d = np.where((h4.index.floor("1D") == signal_time.floor("1D")).values)[0]
        if len(j_d) > 0:
            j_daily = j_d[-1]  # last bar of that day
            daily_atr_pct = atr[min(j_daily + 1, len(atr) - 1)] / H4c[j] * 100
            if filters.get("min_daily_volatility_pct", 0) > 0:
                if daily_atr_pct < filters["min_daily_volatility_pct"]:
                    j += 1
                    continue

        # Filter: Daily SMA filter (close > SMA200 + 0.5%)
        if filters.get("daily_sma_buffer_pct", 0) > 0:
            d1_idx = h4.index.floor("1D")
            if j < len(d1_idx):
                # Rough approximation: use h4 data
                close_over_buffer = H4c[j] > hh[j] * (1 + filters["daily_sma_buffer_pct"] / 100)
                if not close_over_buffer:
                    j += 1
                    continue

        lvl, a = hh[j], atr[j]
        k0 = pos15(t4[j] + pd.Timedelta(hours=4))
        k_end = min(k0 + 96, len(c) - 1)
        k_in, px, fee_in = None, None, t4s.TAKER

        if entry_mode == "next":
            k_in, px = k0, o[k0]
        elif entry_mode == "retest":
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

        # Filter: Stop distance (only trade if stop < max_stop_pct)
        stop = px - 2 * a
        stop_pct = (px - stop) / px * 100
        if filters.get("max_stop_pct", 0) > 0:
            if stop_pct > filters["max_stop_pct"]:
                j += 1
                continue

        risk = px - stop
        funding = 0.0
        k = k_in
        exit_px = None

        while k < len(c) - 1:
            if l[k] <= stop:
                exit_px = min(o[k], stop)
                break
            funding += fund[k]
            if last4[k]:
                j4 = idx4[k]
                if np.isfinite(ll[j4]) and H4c[j4] < ll[j4]:
                    k += 1
                    exit_px = o[k]
                    break
            k += 1

        if exit_px is None:
            break

        cost = fee_in * px + t4s.TAKER * exit_px + funding * px
        r = (exit_px - px - cost) / risk

        # Track losing streak for next iteration
        if r <= 0:
            losing_streak += 1
        else:
            losing_streak = 0

        trades.append({"symbol": sym, "mode": entry_mode, "n_in": n_in,
                      "entry_time": t15[k_in], "exit_time": t15[min(k, len(t15) - 1)],
                      "entry": px, "stop": stop, "exit": exit_px,
                      "risk_pct": risk / px * 100, "r": r, "cost_r": cost / risk,
                      "stop_pct": stop_pct})

        j = t4.searchsorted(t15[min(k, len(t15) - 1)])

    return trades


def main():
    data, prefix = Path(sys.argv[1]), sys.argv[2]

    # Define filter variants
    variants = {
        "baseline": {},
        "no_gold": {"exclude_symbols": ["XAUUSD"]},
        "no_crypto_minors": {"exclude_symbols": ["XAUUSD", "XRPUSDT"]},
        "peak_hours": {"peak_hours_only": True},
        "volatility_gate": {"min_daily_volatility_pct": 1.2},
        "combined": {
            "exclude_symbols": ["XAUUSD"],
            "peak_hours_only": True,
            "min_daily_volatility_pct": 1.2,
        },
    }

    for variant_name, filters in variants.items():
        print(f"\n{'='*60}")
        print(f"Testing: {variant_name}")
        print(f"Filters: {filters if filters else 'none'}")
        print(f"{'='*60}")

        rows = []
        for sym in t4s.SYMBOLS:
            if sym in filters.get("exclude_symbols", []):
                continue

            try:
                m15, h4 = t4s.load(data, sym)
                for n_in, n_out in ((55, 20), (20, 10)):
                    for mode in ("next", "retest", "confirm"):
                        rows += run_filtered(sym, m15, h4, n_in, n_out, mode, filters)
                print(f"{sym}: {len([r for r in rows if r['symbol'] == sym])} trades",
                      file=sys.stderr, flush=True)
            except Exception as e:
                print(f"{sym}: {type(e).__name__}", file=sys.stderr)

        if rows:
            t = pd.DataFrame(rows)
            t["test"] = t.entry_time >= SPLIT

            # Print summary
            for split_name, split_filter in [("2021-24", ~t.test), ("2025-26", t.test)]:
                g = t[split_filter]
                if not g.empty:
                    print(f"{split_name:8s} n={len(g):3d} avg {g.r.mean():+.2f}R "
                          f"win {(g.r > 0).mean():.0%} "
                          f"median_stop {g.stop_pct.median():.1f}%")

            # Save detailed results
            filename = f"{prefix}_{variant_name}.csv"
            t.to_csv(filename, index=False)
            print(f"→ {filename}")


if __name__ == "__main__":
    main()
