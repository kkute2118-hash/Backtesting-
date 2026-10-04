#!/usr/bin/env python3
"""Test 4h trend strategy with partial exit + EMA trailing.

Variants:
  current         original: all exit on 20-low
  partial_ema20   50% at 2R target, 50% trail EMA20
  partial_ema50   50% at 2R target, 50% trail EMA50
  partial_ema100  50% at 2R target, 50% trail EMA100
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


def run_with_partial_ema(sym, m15, h4, n_in, n_out, entry_mode, ema_period=None):
    """Run 4h trend strategy with optional partial exit + EMA trail.

    Args:
        ema_period: None (current strategy) or 20/50/100 (EMA trail period)
    """
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

    # Calculate EMA if requested
    if ema_period:
        ema_4h = h4.close.ewm(span=ema_period, adjust=False).mean().to_numpy()

    trades = []
    j = 220

    while j < len(H4c) - 1:
        if not (trend[j] and np.isfinite(hh[j]) and np.isfinite(atr[j]) and H4c[j] > hh[j]):
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

        stop = px - 2 * a
        risk = px - stop
        target = px + 2 * risk  # 2R target

        # State tracking for partial exit variant
        target_hit = False
        half_qty_closed_at = None
        exit_px = None
        funding = 0.0
        k = k_in

        while k < len(c) - 1:
            # Current 4h index
            j_h4 = idx4[k]

            # Check if hit 2R target (for partial exit variants)
            if ema_period and not target_hit:
                # Target is between the low and close of the candle
                if (l[k] <= target <= h[k]) or (l[k] <= target and k == k_in):
                    target_hit = True
                    half_qty_closed_at = target
                    # First 50% exits at target
                    # Don't immediately exit k - continue holding 50%

            # Check exit conditions
            # Original stop always applies (to both halves)
            if l[k] <= stop:
                exit_px = min(o[k], stop)
                break

            # 4h close below 20-period low (original exit) - applies to remaining 50%
            if np.isfinite(ll[j_h4]) and H4c[j_h4] < ll[j_h4]:
                # If partial variant and target was hit, this is for the remaining 50%
                if ema_period and target_hit:
                    exit_px = o[min(k + 1, len(c) - 1)]
                else:
                    k += 1
                    exit_px = o[k] if k < len(o) else o[-1]
                break

            # EMA trail exit (for partial variant)
            if ema_period and target_hit and np.isfinite(ema_4h[j_h4]):
                # Exit remaining 50% when 4h close closes below EMA
                if H4c[j_h4] < ema_4h[j_h4]:
                    exit_px = c[k]
                    break

            funding += fund[k]
            k += 1

        if exit_px is None:
            break

        # Calculate returns for partial exit variant
        if ema_period and target_hit and half_qty_closed_at:
            # First 50% closed at target
            r_half1 = (target - px) / risk
            # Second 50% closed at exit_px
            r_half2 = (exit_px - px) / risk
            # Average of the two halves
            r = (r_half1 + r_half2) / 2
            exit_reason = "partial_ema" + str(ema_period)
        else:
            # Current strategy - all position exits at once
            cost = fee_in * px + t4s.TAKER * exit_px + funding * px
            r = (exit_px - px - cost) / risk
            exit_reason = "current"

        trades.append({
            "symbol": sym,
            "mode": entry_mode,
            "n_in": n_in,
            "entry_time": t15[k_in],
            "exit_time": t15[min(k, len(t15) - 1)],
            "entry": px,
            "stop": stop,
            "target": target if ema_period else None,
            "exit": exit_px,
            "risk_pct": risk / px * 100,
            "r": r,
            "exit_reason": exit_reason
        })

        j = t4.searchsorted(t15[min(k, len(t15) - 1)])

    return trades


def main():
    data, prefix = Path(sys.argv[1]), sys.argv[2]

    variants = {
        "current": None,
        "partial_ema20": 20,
        "partial_ema50": 50,
        "partial_ema100": 100,
    }

    for variant_name, ema_period in variants.items():
        print(f"\n{'='*70}")
        print(f"Variant: {variant_name}")
        if ema_period:
            print(f"Strategy: Partial exit (50% at 2R) + EMA{ema_period} trail (50%)")
        else:
            print(f"Strategy: Current (all exit on 20-low or stop)")
        print(f"{'='*70}")

        rows = []
        for sym in t4s.SYMBOLS:
            try:
                m15, h4 = t4s.load(data, sym)
                for n_in, n_out in ((55, 20), (20, 10)):
                    for mode in ("next", "retest", "confirm"):
                        rows += run_with_partial_ema(sym, m15, h4, n_in, n_out, mode, ema_period)
                print(f"{sym}: {len([r for r in rows if r['symbol'] == sym])} trades",
                      file=sys.stderr, flush=True)
            except Exception as e:
                print(f"{sym}: {type(e).__name__}: {e}", file=sys.stderr)

        if not rows:
            print("No trades generated")
            continue

        t = pd.DataFrame(rows)
        t["test"] = t.entry_time >= SPLIT

        print(f"\nTotal trades: {len(t)}")
        print(f"\nBy period:")

        for period_name, period_filter in [("2021-24", ~t.test), ("2025-26", t.test)]:
            g = t[period_filter]
            if not g.empty:
                print(f"\n{period_name}:")
                print(f"  Trades:     {len(g)}")
                print(f"  Winners:    {(g.r > 0).sum()} ({(g.r > 0).mean():.1%})")
                print(f"  Losers:     {(g.r <= 0).sum()} ({(g.r <= 0).mean():.1%})")
                print(f"  Avg R:      {g.r.mean():+.2f}R")
                print(f"  Median R:   {g.r.median():+.2f}R")
                print(f"  Total R:    {g.r.sum():+.0f}R")
                print(f"  Avg winner: {g[g.r > 0].r.mean():+.2f}R ({len(g[g.r > 0])} trades)")
                print(f"  Avg loser:  {g[g.r <= 0].r.mean():+.2f}R ({len(g[g.r <= 0])} trades)")
                print(f"  Std dev:    {g.r.std():.2f}R")

                # Estimate account value at 2% risk
                annual_r = g.r.sum() * (56 / len(g))  # 56 trades/year
                years = len(g) / 56 if len(g) > 0 else 1
                start_equity = 10_000
                risk_per_trade = 0.02

                # Rough compounding estimate
                avg_stop_pct = g.risk_pct.median() / 100
                compound_equity = start_equity
                for _ in range(len(g)):
                    pos_size_x = (risk_per_trade / avg_stop_pct) if avg_stop_pct > 0 else 1
                    pos_size_x = min(pos_size_x, 5.0)  # cap at 5x
                    compound_equity *= (1 + g.r.mean() * risk_per_trade / pos_size_x)

                print(f"  Est. Rs @2%: Rs {compound_equity:,.0f} (rough)")

        # Save to CSV
        filename = f"{prefix}_{variant_name}.csv"
        t.to_csv(filename, index=False)
        print(f"\n✓ Saved: {filename}")


if __name__ == "__main__":
    main()
