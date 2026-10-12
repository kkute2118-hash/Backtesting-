# Step 16: Rulebook v1 (RB1), the owner's level + candle rulebook

**What.** `backend/app/engine/rb1/` implements the owner's rulebook as exact rules:

- **Levels**, scored for confluence: PDH/PDL (3), VAH/VAL (2), 15m/1H order
  blocks (2), triple-touch zones (2), CDH/CDL (1).
- **Candles**: power and rejection (LPR/HPR).
- **Bias**: 1H structure.
- **Delta**: Binance taker-buy delta with absorption.
- **Setups**, in priority order: A sweep, B triple touch, C pullback,
  D N-breakout.
- **Risk**: 1% per trade, 2% on five-star trades, at most 2 trades and 2
  losses a day, a 2.5% daily risk cap and a 5% daily profit stop.
- **Management**: at least 2R, stop to break-even at 50% of the way, swing
  trail from 80%.

Every constant is tagged SOURCE_STATED / DERIVED / NEEDS_TUNING in
`config.py`.

**Test.** Real 5-minute prices, Jan 2021 - Oct 2026: BTC, ETH, SOL, XRP and BNB
perpetuals (Binance, with taker volume), gold, EUR/USD and GBP/USD (Dukascopy,
recorded spreads). Each instrument trades its own $10,000 account, using closed
15-minute bars only. Tests: `backend/tests/test_rb1.py`, including a no
look-ahead check.

## Result: loses on every instrument and every setup

| | trades | win | avg R (after costs) | avg R before costs |
|---|---|---|---|---|
| 2021-24 | 6,536 | 22% | -0.22 | -0.06 |
| 2025-26 | 2,763 | 24% | -0.16 | +0.02 |
| last 12 months | 1,594 | 25% | -0.14 | +0.04 |

**By instrument** (avg R): BTC -0.31, BNB -0.26, ETH -0.22, XRP -0.20,
SOL -0.16, gold -0.15, EUR/USD -0.13, GBP/USD -0.13. Every $10,000 account
ends below $3,000. BTC ends at $19.

**By setup:**

| setup | trades | avg R |
|---|---|---|
| A sweep | 230 | -0.40 |
| C pullback | 5,072 | -0.29 |
| D N-breakout | 3,995 | -0.09 |
| B triple touch | 2 | - |

**Other cuts:**

- Higher confluence does not help: 2 = -0.23R, 4 = -0.17R, 7+ = -0.26R.
- Delta-confirmed trades (crypto) do better but still lose: 69 trades,
  -0.07R.
- Rejection candles (LPR -0.35R, HPR -0.24R) do worse than power candles
  (-0.08R).

**Why.** Before costs the edge is about zero (-0.04R a trade). Costs take
about 0.17R more, because 15-minute stops are tight: a 0.15% stop on BTC means
the 0.14% round-trip fee is about 1R.

**One assumption checked.** The rulebook says the target is "the next opposing
level". Taking the nearest one rejects most sweeps (only 230 trades). Taking
the first level that gives 2R instead makes sweeps fire 7,900 times, but the
result is the same: -0.22R in 2021-24 and -0.23R in 2025-26.

**Verdict.** Not adopted (the evidence rule needs a profit in 2021-24 that
holds in 2025-26; RB1 makes neither). No live scanner, API or page is built
for it. Its parts (levels, candle classes, delta) are tested and can be
reused if a variant is worth trying.
