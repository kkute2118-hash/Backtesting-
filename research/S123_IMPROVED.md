# S1-S3 improved with S6's market traits (29 Sep 2026)

Scripts: `scripts/s123_improve.py` (trade level) and `scripts/s123_account.py`
(Rs 1 lakh account). Both read-only.

## The rule

A signal from S1, S2 or S3 is taken only when:

- market breadth is >= 0.50;
- the stock is >= 60% above its 52-week low;
- the stock is within 15% of its 52-week high.

This replaces their old ATR/turnover entry filter
(`core.ENTRY_FILTER_BY_STRATEGY`, rule `s6traits`, `core.s6_traits_verdict`).
The live scan and `historical_entry_verdict`, and so every backtest replay,
share it.

## Why it is not curve-fitting

- A blind search looked only at 2022-24 and tried each of ~40 signal-day
  readings above or below its quantiles. For all three strategies it picked
  **market breadth** as the best extra rule, rediscovering S6's gate without
  being given it. It still helped on 2025-26, which the search never saw.
- The search's second rules (MACD thresholds) failed on 2025-26 and were
  rejected.
- S6's three traits together helped every strategy in both periods. Average R
  per trade, from raw signals:

| | As it was, 2022-24 | As it was, 2025-26 | + S6 traits, 2022-24 | + S6 traits, 2025-26 |
|---|---|---|---|---|
| S1 | +0.32 | -0.03 | +0.62 | +0.39 |
| S2 | +0.51 | +0.01 | +0.88 | +0.25 |
| S3 | +0.25 | -0.06 | +0.49 | +0.71 |

## Rs 1 lakh account, Jan 2022 - Sep 2026

One pool, 10 slots, 1% risk, Indian costs, one position per stock.

| Book | Final | CAGR | Worst drop | Win % | 2025 |
|---|---|---|---|---|---|
| S1 as it was | Rs 0.95 L | -1.0% | -51% | 29% | -29% |
| **S1 + S6 traits** | **Rs 2.43 L** | **20.7%** | **-17%** | 41% | +3% |
| S2 as it was | Rs 2.04 L | 16.3% | -24% | 38% | -9% |
| **S2 + S6 traits** | **Rs 2.79 L** | **24.2%** | **-11%** | 49% | +9% |
| S3 as it was | Rs 1.02 L | 0.4% | -41% | 29% | -28% |
| **S3 + S6 traits** | **Rs 2.75 L** | **23.9%** | **-10%** | 44% | +11% |
| S1+S2+S3 + S6 traits | Rs 2.56 L | 22.0% | -16% | 40% | +1% |
| S6 alone | Rs 2.64 L | 22.8% | -13% | 48% | +7% |
| S4+S5+S6 (before this) | Rs 3.34 L | 29.1% | -35% | 36% | +11% |
| S4+S5+S6 + improved S1-S3 | Rs 3.44 L | 29.9% | -38% | 38% | +0% |

- **Each strategy on its own goes from broken to good.** S1 and S3 turn from
  roughly zero to about 21-24% a year, with their worst drop cut from 41-51% to
  10-17%. On their own they now match S6.
- **Added to S4+S5+S6 they change little.** The combined book gains 0.8 points
  a year, and its worst drop deepens by 3 points. Like S6, they trade only
  when breadth is high, so they compete with S5 and S6 for the same slots in
  the same weeks.
- **Decision.** The owner asked for the improved S1-S3 in the scanner, and
  they are in. The account result above is why they get slot priority after
  S4-S6 (`core.STRATEGY_SLOT_PRIORITY`).
- **Open question.** A lower-drawdown book, such as S6 + S2 + S3 (all gated),
  has not been tested yet.
