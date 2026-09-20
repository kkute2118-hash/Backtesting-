"""Indian equity costs applied to the filter result.

Lecture 13 is half about this and the argument is structural, not incidental:
STT is NOT deductible against short-term capital gains, so a book that looks
profitable on risk-reward can be a net loss after charges. His worked example
turns a 4 lakh gain into a 2.8 lakh loss.

"it is entirely possible the STT will accumulate in such a huge amount that by
end of the year, even though you were profitable from your perspective of
risk-reward calculations and win rate, the way the charges structure is, you
will end up in losses."

So a backtest of his method that ignores costs is testing the wrong thing.

Rates are NSE delivery equity as of 2026 and are set here in one place so they
can be corrected to whatever the user's broker actually charges.
"""

from __future__ import annotations
import sys
import numpy as np
import pandas as pd

# Per side unless noted. Fractions of turnover.
BROKERAGE = 0.0003        # 0.03%, capped at Rs20/order at most discount brokers
BROKERAGE_CAP = 20.0
STT_BUY = 0.001           # 0.1% delivery, NOT deductible
STT_SELL = 0.001
EXCHANGE = 0.0000297      # NSE transaction charge
SEBI = 0.000001
STAMP_BUY = 0.00015       # buy side only
GST = 0.18                # on brokerage + exchange + SEBI

# Slippage is the one that is not a published rate. The author is explicit
# that it is real and that it scales with size - "1% at times goes in buying
# and selling, combined slippage" on a good position size. Two scenarios so
# the conclusion does not rest on one guess.
SLIPPAGE = {"optimistic": 0.0005, "realistic": 0.0015, "pessimistic": 0.0030}


def round_trip_pct(notional: float, slip: float) -> float:
    """Total round-trip cost as a percentage of notional."""
    br = min(notional * BROKERAGE, BROKERAGE_CAP) * 2
    stt = notional * (STT_BUY + STT_SELL)
    exch = notional * EXCHANGE * 2
    sebi = notional * SEBI * 2
    stamp = notional * STAMP_BUY
    gst = (br + exch + sebi) * GST
    slippage = notional * slip * 2
    return (br + stt + exch + sebi + stamp + gst + slippage) / notional * 100


def main():
    d = pd.read_csv("research/trader_methodology/rank_results.csv")
    te = d[d.year == 2026].copy()

    # The filter, with bands chosen on 2025 alone.
    keep = (~te.single_tower.astype(bool)) & te.cb_purity.between(0.30, 0.70) \
        & te.avg_turnover_20.between(100, 400)

    # Position size follows the author: 35-40% of capital to start. On
    # Rs 1,00,000 that is Rs 35,000-40,000 a trade, which is well past the
    # Rs 20 brokerage cap, so brokerage is effectively flat per order.
    notional = 35000.0

    print(f"Notional per trade: Rs {notional:,.0f}  (his stated 35-40% of capital "
          f"on a Rs 1 lakh book)\n")
    print(f"{'slippage':14s} {'round trip':>11s} {'kept net':>11s} {'dropped net':>12s} "
          f"{'all net':>10s}")
    print("-" * 64)
    for name, slip in SLIPPAGE.items():
        rt = round_trip_pct(notional, slip)
        k = te[keep].ret.mean() - rt
        dr = te[~keep].ret.mean() - rt
        al = te.ret.mean() - rt
        print(f"{name:14s} {rt:10.3f}% {k:+10.3f}% {dr:+11.3f}% {al:+9.3f}%")

    rt = round_trip_pct(notional, SLIPPAGE["realistic"])
    print()
    print("Breakdown at realistic slippage, per round trip:")
    br = min(notional * BROKERAGE, BROKERAGE_CAP) * 2
    parts = {
        "brokerage (capped)": br,
        "STT (non-deductible)": notional * (STT_BUY + STT_SELL),
        "exchange + SEBI": notional * (EXCHANGE + SEBI) * 2,
        "stamp duty": notional * STAMP_BUY,
        "GST": (br + notional * (EXCHANGE + SEBI) * 2) * GST,
        "slippage": notional * SLIPPAGE["realistic"] * 2,
    }
    for k2, v in parts.items():
        print(f"  {k2:24s} Rs {v:8.2f}   {v/notional*100:6.3f}%")
    print(f"  {'TOTAL':24s} Rs {sum(parts.values()):8.2f}   {rt:6.3f}%")

    print()
    print("Trade counts and annual cost drag, 2026:")
    n_all, n_keep = len(te), int(keep.sum())
    print(f"  all signals   {n_all:6d} trades")
    print(f"  filtered      {n_keep:6d} trades  ({100*n_keep/n_all:.0f}% of them)")
    print()
    print("  Those are signals, not positions. With 3 concurrent slots and a")
    print("  median hold of 18 bars, a year takes roughly 40-50 trades - so the")
    print("  per-trade figures above are what matters, not the signal count.")

    print()
    print("STT specifically, since it is the one that is not deductible:")
    stt_pct = (STT_BUY + STT_SELL) * 100
    print(f"  {stt_pct:.3f}% per round trip. On 45 trades a year at Rs 35,000 that is")
    print(f"  Rs {0.002 * notional * 45:,.0f} of non-deductible cost against a Rs 1,00,000 book.")


if __name__ == "__main__":
    main()
