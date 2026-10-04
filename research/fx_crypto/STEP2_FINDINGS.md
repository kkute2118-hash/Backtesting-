# Step 2: refining the liquidity framework (4 Oct 2026)

Runs: scripts/liquidity_step2_runs.py (all symbols, limit and LTF entries,
crypto with taker and maker fees incl. 18% GST), analysis:
scripts/liquidity_step2_analysis.py. Every choice below was made on 2021-24
and then checked on 2025-26.

## Chosen on 2021-24

| candidate (forex + gold, limit entry) | 2021-24 | 2025-26 |
|---|---|---|
| run → retest, all hours | −0.04R | −0.03R |
| run → retest, overlap 17:30-21:30 IST | +0.19R | +0.23R |
| **A: run → retest, London open (11:30-13:30 IST) + NY morning (17:30-21:30 IST)** | **+0.24R, PF 1.34, 1,863** | **+0.17R, PF 1.23, 866** |
| A + strong run candle (body ≥ 1.2 ATR) | +0.23R (no better: not adopted) | +0.20R |
| A with LTF micro-MSB entry | +0.11R | +0.21R |
| sweep/grab reversal, same hours | +0.02R | −0.15R (not adopted) |
| **B: A with the framework's own score ≥ 65** | **+0.48R, PF ~1.7, 333** | **+0.47R, 152** |

A by year: +0.26, +0.23, +0.21, +0.28, +0.24, +0.07R (2026 to 2 Oct).
B by year: +0.54, +0.66, +0.30, +0.44, +0.73, +0.14R.

The 65 threshold is the framework's own "watchlist" line, not fitted here.
A score refitted by regression on 2021-24 ranked trades there but not in
2025-26 (+0.14/+0.18/+0.17R by tercile), so it was not adopted.

## Costs decide it

Spread multiple vs Dukascopy (A / B, 2025-26): x1 +0.17/+0.47R, x2 +0.05/+0.34R,
x3 −0.06/+0.22R, x5 −0.29/−0.03R. A retail standard account (about 5x on
EURUSD) kills both; B survives up to about 3x. Only a raw-spread account or
a venue with similar costs keeps the edge.

## Crypto

Taker fees (0.07% a side incl. GST and slippage) lose everywhere. With maker
fees on entries and targets, run → retest in the same hours with a strong run
candle: +0.08R in both periods. Too thin to trade; watch only.

## Account (B, compounding, one sequence, no live frictions)

Rs 10,000 at 0.5% risk: Rs 30,438, worst drawdown −9%. At 1%: Rs 85,886,
worst −17%. Leverage needed at 1% risk: median 15x, 90th percentile 35x.
These are backtest figures with optimistic limit fills (touch = filled).
